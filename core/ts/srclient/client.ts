// Shared client for api.steadyrouter.com: chat, images, video tasks, safe downloads.
// Mirrors core/python/srclient/client.py. Rules every platform relies on:
// - A link from an upstream is downloaded at once and never handed to the user.
// - A reference image the caller links is downloaded only through fetchReference, under the same rules as any download.
// - The API key only ever goes to the gateway, never to a download host (the transport adds it only when `auth` is true).
// - Errors are scrubbed (see errors.ts), so they are safe to display.
// The platform supplies the transport (n8n helpers, fetch in a Worker, ...), so this file imports nothing platform-specific.

import { classify, familyOf, matchesAny, type Category, type PricingRow } from './classify';
import {
	FileTooLarge,
	SRError,
	ValidationError,
	VideoFailed,
	VideoStillRunning,
	fromResponse,
	scrub,
} from './errors';
import * as gen from './generated';

export const API_BASE: string = gen.SITE.api_base;
export const MAX_FILE_BYTES = 50 * 1024 * 1024;
export const MAX_VIDEO_BYTES = 200 * 1024 * 1024;
export const IMAGE_TIMEOUT_MS = 300_000; // the public docs tell clients to allow 300 seconds
export const SHORT_TIMEOUT_MS = 30_000;
export const CHAT_TIMEOUT_MS = 300_000;
export const DOWNLOAD_TIMEOUT_MS = 120_000;
export const POLL_SECONDS = 12; // the public video guide says every 10 to 15 seconds
export const VIDEO_WAIT_SECONDS = 480;
const MAX_REDIRECTS = 3;
const REDIRECTS = new Set([301, 302, 303, 307, 308]);
const MD_IMAGE = /!\[[^\]]*\]\(\s*(data:image\/[^)\s]+|https?:\/\/[^)\s]+)\s*\)/g;
const BARE_DATA = /data:image\/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=_-]+/g;
const BARE_LINK = /https?:\/\/[^\s"'<>)\]]+/g;

// ---- transport contract ----

export interface FormFile {
	field: string;
	name: string;
	mime: string;
	data: Uint8Array;
}

export interface HttpRequest {
	method: 'GET' | 'POST';
	url: string;
	/** Add the API key. Only ever true for the gateway. */
	auth: boolean;
	json?: unknown;
	form?: { fields: Record<string, string>; files: FormFile[] };
	timeoutMs: number;
	/** Return the body as bytes instead of parsed JSON. */
	binary?: boolean;
	maxBytes?: number;
}

export interface HttpReply {
	status: number;
	headers: Record<string, string | undefined>;
	/** Parsed JSON, or undefined when the body was not JSON. Not set for binary requests. */
	body?: unknown;
	bytes?: Uint8Array;
}

/**
 * Must not follow redirects, must not throw on HTTP error statuses, and must throw
 * TransportError when the request could not be made or timed out.
 */
export interface Transport {
	request(req: HttpRequest): Promise<HttpReply>;
	sleep(ms: number): Promise<void>;
	now(): number;
}

export class TransportError extends Error {
	readonly timeout: boolean;

	constructor(message: string, timeout = false) {
		super(message);
		this.name = 'TransportError';
		this.timeout = timeout;
	}
}

// ---- files ----

export interface GeneratedFile {
	data: Uint8Array;
	mime: string;
}

const EXTENSIONS: Record<string, string> = {
	'image/png': 'png',
	'image/jpeg': 'jpg',
	'image/webp': 'webp',
	'image/gif': 'gif',
	'video/mp4': 'mp4',
	'video/webm': 'webm',
};

export function extensionOf(mime: string): string {
	return EXTENSIONS[mime] ?? 'bin';
}

function startsWith(data: Uint8Array, bytes: number[], offset = 0): boolean {
	return bytes.every((b, i) => data[offset + i] === b);
}

const ascii = (text: string) => Array.from(text, (c) => c.charCodeAt(0));

export function sniff(data: Uint8Array): string | null {
	if (startsWith(data, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return 'image/png';
	if (startsWith(data, [0xff, 0xd8, 0xff])) return 'image/jpeg';
	if (startsWith(data, ascii('RIFF')) && startsWith(data, ascii('WEBP'), 8)) return 'image/webp';
	if (startsWith(data, ascii('GIF87a')) || startsWith(data, ascii('GIF89a'))) return 'image/gif';
	if (startsWith(data, ascii('ftyp'), 4)) return 'video/mp4';
	if (startsWith(data, [0x1a, 0x45, 0xdf, 0xa3])) return 'video/webm';
	return null;
}

export function decodeBase64(text: string): Uint8Array {
	const clean = text.replace(/-/g, '+').replace(/_/g, '/').replace(/[^A-Za-z0-9+/]/g, '');
	const binary = atob(clean + '==='.slice((clean.length + 3) % 4));
	const out = new Uint8Array(binary.length);
	for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
	return out;
}

export function encodeBase64(data: Uint8Array): string {
	let binary = '';
	for (let i = 0; i < data.length; i += 0x8000) {
		binary += String.fromCharCode.apply(null, Array.from(data.subarray(i, i + 0x8000)));
	}
	return btoa(binary);
}

export function tryDecodeBase64(text: string): Uint8Array | null {
	try {
		return decodeBase64(text);
	} catch {
		return null;
	}
}

/** Image types an image edit takes as a reference (the OpenAI edits format: PNG, JPEG, WebP). */
const REFERENCE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp']);
export const REF_UNREADABLE =
	'A reference image could not be downloaded, or it is not a PNG, JPEG or WebP image. Use a public https link to the image file itself.';

/** Bytes of a reference image, checked by their content (not by the link or a header). */
export function referenceImage(data: Uint8Array): GeneratedFile {
	const mime = sniff(data);
	if (!mime || !REFERENCE_TYPES.has(mime)) throw new ValidationError(REF_UNREADABLE);
	return { data, mime };
}

function parseUrl(url: string, base?: string): URL | null {
	try {
		return new URL(url, base);
	} catch {
		return null;
	}
}

// ---- download host checks ----

function ipv4Parts(host: string): number[] | null {
	const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
	if (!m) return null;
	const parts = m.slice(1).map(Number);
	return parts.every((p) => p <= 255) ? parts : null;
}

function privateIpv4([a, b]: number[]): boolean {
	if (a === 198 && (b === 18 || b === 19)) return false; // proxies in fake-IP mode (see client.py)
	return (
		a === 0 || a === 10 || a === 127 || a >= 224 ||
		(a === 100 && b >= 64 && b <= 127) ||
		(a === 169 && b === 254) ||
		(a === 172 && b >= 16 && b <= 31) ||
		(a === 192 && (b === 168 || b === 0))
	);
}

/**
 * Refuse hosts that are private by name or by IP literal. Needs no DNS, so it works where DNS lookups are not
 * allowed (n8n Cloud); the platform adds DNS-based checks where it can.
 */
export function literalHostCheck(hostname: string): void {
	const host = hostname.toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '');
	const fail = () => {
		throw new SRError('The generated file could not be downloaded.');
	};
	if (!host || host === 'localhost' || /\.(localhost|local|internal|home|lan)$/.test(host)) fail();
	const v4 = ipv4Parts(host);
	if (v4 && privateIpv4(v4)) fail();
	if (host.includes(':')) {
		const first = parseInt(host.split(':')[0] || '0', 16);
		if (!(first >= 0x2000 && first <= 0x3fff)) fail(); // only global unicast IPv6 literals
	}
}

export function videoDownloadHint(taskId: string, apiBase: string = API_BASE): string {
	return (
		`Task ID: ${taskId}\n` +
		'Download it from SteadyRouter with your API key (the request must carry the key):\n' +
		`GET ${apiBase}/v1/videos/${taskId}/content with the header Authorization: Bearer YOUR_API_KEY\n` +
		'Videos are kept for a limited time only, so save yours soon.'
	);
}

// ---- model lists ----

export async function pricingModels(transport: Transport, url: string = gen.SITE.pricing_api): Promise<PricingRow[]> {
	const reply = await transport.request({ method: 'GET', url, auth: false, timeoutMs: SHORT_TIMEOUT_MS });
	if (reply.status !== 200) throw new TransportError(`pricing returned ${reply.status}`);
	const data = (reply.body as { data?: unknown })?.data;
	if (!Array.isArray(data)) throw new TransportError('pricing reply had no data');
	return data
		.filter((r): r is PricingRow => typeof r?.model_name === 'string')
		.map((r) => ({
			model_name: r.model_name,
			tags: r.tags,
			supported_endpoint_types: r.supported_endpoint_types,
			description: r.description,
		}));
}

/** Models for a dropdown: live list first, the list shipped in the package if that fails. */
export async function listModels(
	category: Category,
	options: { family?: string | null; exclude?: readonly string[]; fetch?: () => Promise<PricingRow[]> } = {},
): Promise<string[]> {
	const skip = new Set(options.exclude ?? []);
	let names: string[] = [];
	if (options.fetch) {
		try {
			const rows = await options.fetch();
			names = rows
				.filter((r) => classify(r, gen.CATEGORY_OVERRIDES) === category)
				.filter((r) => !options.family || familyOf(r.model_name, gen.FAMILIES) === options.family)
				.map((r) => r.model_name);
		} catch {
			names = [];
		}
	}
	if (!names.length) {
		names = gen.SHIPPED_MODELS.filter(
			(m) => m.category === category && (!options.family || m.family === options.family),
		).map((m) => m.name);
	}
	return names.filter((n) => !skip.has(n)).sort();
}

// ---- the client ----

export interface ChatMessage {
	role: 'system' | 'user' | 'assistant';
	content: string | Array<Record<string, unknown>>;
}

export interface ChatOptions {
	temperature?: number;
	maxTokens?: number;
	jsonOutput?: boolean;
}

export interface ChatResult {
	text: string;
	model: string;
	finishReason: string;
	usage: Record<string, unknown>;
	raw: Record<string, unknown>;
}

export interface ImageOptions {
	size?: string;
	quality?: string;
	n?: number;
	aspectRatio?: string;
	imageSize?: string;
	images?: GeneratedFile[];
	/** Reference images as links the gateway fetches itself (chat image models only). The client never downloads them. */
	imageUrls?: string[];
	limit?: number;
}

export interface VideoOptions {
	resolution?: string;
	seconds?: number;
	startImage?: string;
}

export interface VideoStatus {
	taskId: string;
	status: string;
	progress: string;
	failReason: string;
	done: boolean;
	failed: boolean;
}

export interface ClientOptions {
	baseUrl?: string;
	/** Only used to scrub the key out of error text; the transport adds it to requests. */
	secret?: string;
	checkHost?: (hostname: string) => void | Promise<void>;
	httpsOnly?: boolean;
	pollSeconds?: number;
	videoWaitSeconds?: number;
	/** Base64 decoder to use instead of the built-in one (a Worker passes a faster, native one). Null = unreadable. */
	decode?: (text: string) => Uint8Array | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function inner(body: Record<string, unknown>): Record<string, unknown> {
	return isRecord(body.data) ? body.data : body;
}

export class SRClient {
	readonly baseUrl: string;
	private readonly t: Transport;
	private readonly secret?: string;
	private readonly checkHost: (hostname: string) => void | Promise<void>;
	private readonly httpsOnly: boolean;
	private readonly pollSeconds: number;
	private readonly videoWaitSeconds: number;
	private readonly decodeText: (text: string) => Uint8Array | null;
	// Upstream links stay here, keyed by task, and are never returned to callers.
	private readonly resultUrls = new Map<string, string>();

	constructor(transport: Transport, options: ClientOptions = {}) {
		this.t = transport;
		this.baseUrl = (options.baseUrl ?? API_BASE).replace(/\/+$/, '');
		this.secret = options.secret;
		this.checkHost = options.checkHost ?? literalHostCheck;
		this.httpsOnly = options.httpsOnly ?? true;
		this.pollSeconds = options.pollSeconds ?? POLL_SECONDS;
		this.videoWaitSeconds = options.videoWaitSeconds ?? VIDEO_WAIT_SECONDS;
		this.decodeText = options.decode ?? tryDecodeBase64;
	}

	// ---- transport ----

	// Errors are caught as values and turned into SRError outside the catch blocks: platforms (n8n) wrap every
	// SRError in their own error type at the node boundary, and their linters expect catch blocks to do only that.
	private async attempt(req: HttpRequest): Promise<HttpReply | { failure: unknown }> {
		try {
			return await this.t.request(req);
		} catch (err) {
			return { failure: err };
		}
	}

	private async send(req: HttpRequest): Promise<HttpReply> {
		const reply = await this.attempt(req);
		if (!('failure' in reply)) return reply;
		const err = reply.failure;
		if (err instanceof SRError) throw err;
		if (err instanceof TransportError && err.timeout) throw new SRError('The request timed out. Try again in a little while.');
		throw new SRError('Could not reach SteadyRouter. Check the network and try again.');
	}

	private async call(
		method: 'GET' | 'POST',
		path: string,
		extra: Partial<Pick<HttpRequest, 'json' | 'form' | 'timeoutMs'>> = {},
	): Promise<Record<string, unknown>> {
		const reply = await this.send({
			method,
			url: this.baseUrl + path,
			auth: true,
			timeoutMs: extra.timeoutMs ?? SHORT_TIMEOUT_MS,
			json: extra.json,
			form: extra.form,
		});
		if (reply.status >= 400 || REDIRECTS.has(reply.status)) throw fromResponse(reply.status, reply.body, this.secret);
		if (!isRecord(reply.body)) {
			throw new SRError('SteadyRouter returned a reply that could not be read.', { status: reply.status });
		}
		return reply.body;
	}

	private capped(bytes: Uint8Array | undefined, limit: number): Uint8Array {
		const data = bytes ?? new Uint8Array();
		if (data.length > limit) throw new FileTooLarge('The file is larger than the size limit.', limit);
		return data;
	}

	private async checkDownloadUrl(url: string): Promise<void> {
		const parts = parseUrl(url);
		if (!parts) throw new SRError('The generated file could not be downloaded.');
		if (parts.protocol !== 'https:' && this.httpsOnly) throw new SRError('The generated file could not be downloaded.');
		if (!['https:', 'http:'].includes(parts.protocol) || !parts.hostname) {
			throw new SRError('The generated file could not be downloaded.');
		}
		await this.checkHost(parts.hostname);
	}

	/** Fetch a link from an upstream: no key, https only, public hosts, bounded size and redirects. */
	private async downloadPublic(url: string, limit: number): Promise<Uint8Array> {
		let target = url;
		for (let hop = 0; hop <= MAX_REDIRECTS; hop++) {
			await this.checkDownloadUrl(target);
			const reply = await this.attempt({
				method: 'GET',
				url: target,
				auth: false,
				binary: true,
				maxBytes: limit,
				timeoutMs: DOWNLOAD_TIMEOUT_MS,
			});
			if ('failure' in reply) {
				if (reply.failure instanceof FileTooLarge) throw reply.failure;
				throw new SRError('The generated file could not be downloaded.');
			}
			if (REDIRECTS.has(reply.status)) {
				target = new URL(reply.headers.location ?? '', target).toString();
				continue;
			}
			if (reply.status !== 200) throw new SRError('The generated file could not be downloaded.');
			return this.capped(reply.bytes, limit);
		}
		throw new SRError('The generated file could not be downloaded.');
	}

	/**
	 * Download a reference image the caller linked, for an image edit (images in generateImage): no key, https only,
	 * public hosts, at most `limit` bytes and a few redirects, and it must be a PNG, JPEG or WebP image. Anything else
	 * throws ValidationError(REF_UNREADABLE); too large throws FileTooLarge. Call checkKey() first, so a wrong key
	 * costs no download.
	 */
	async fetchReference(url: string, limit: number): Promise<GeneratedFile> {
		const got = await this.downloadPublic(url, limit).then(
			(data) => ({ data }),
			(failure: unknown) => ({ failure }),
		);
		if ('failure' in got) {
			if (got.failure instanceof FileTooLarge) throw got.failure;
			throw new ValidationError(REF_UNREADABLE);
		}
		return referenceImage(got.data);
	}

	/** GET /v1/models costs nothing. A wrong key throws SRError. */
	async checkKey(): Promise<void> {
		await this.call('GET', '/v1/models');
	}

	// ---- chat ----

	async chat(model: string, messages: ChatMessage[], options: ChatOptions = {}): Promise<ChatResult> {
		if (!model) throw new ValidationError('Choose a model.');
		if (!messages.length) throw new ValidationError('A prompt is required.');
		const payload: Record<string, unknown> = { model, messages, stream: false };
		if (options.temperature !== undefined) payload.temperature = options.temperature;
		if (options.maxTokens) payload.max_completion_tokens = options.maxTokens;
		if (options.jsonOutput) payload.response_format = { type: 'json_object' };
		const body = await this.call('POST', '/v1/chat/completions', { json: payload, timeoutMs: CHAT_TIMEOUT_MS });
		const choice = Array.isArray(body.choices) && isRecord(body.choices[0]) ? body.choices[0] : {};
		const message = isRecord(choice.message) ? choice.message : {};
		const content = message.content;
		const text = Array.isArray(content)
			? content
					.filter((p) => isRecord(p) && p.type === 'text')
					.map((p) => String((p as Record<string, unknown>).text ?? ''))
					.join('')
			: String(content ?? '');
		return {
			text,
			model: String(body.model ?? model),
			finishReason: String(choice.finish_reason ?? ''),
			usage: isRecord(body.usage) ? body.usage : {},
			raw: body,
		};
	}

	// ---- images ----

	private asImage(data: Uint8Array, limit: number): GeneratedFile {
		if (data.length > limit) throw new FileTooLarge('The file is larger than the size limit.', limit);
		const mime = sniff(data);
		if (!mime || !mime.startsWith('image/')) throw new SRError('The model returned an image that could not be read.');
		return { data, mime };
	}

	private decode(text: string): Uint8Array {
		const data = this.decodeText(text);
		if (!data) throw new SRError('The model returned an image that could not be read.');
		return data;
	}

	private async fileFromRef(ref: string, limit: number): Promise<GeneratedFile> {
		const data = ref.startsWith('data:') ? this.decode(ref.split(',', 2)[1] ?? '') : await this.downloadPublic(ref, limit);
		return this.asImage(data, limit);
	}

	private async imagesFromReply(body: Record<string, unknown>, limit: number): Promise<GeneratedFile[]> {
		const files: GeneratedFile[] = [];
		for (const item of Array.isArray(body.data) ? body.data : []) {
			if (!isRecord(item)) continue;
			if (item.b64_json) files.push(this.asImage(this.decode(String(item.b64_json)), limit));
			else if (item.url) files.push(await this.fileFromRef(String(item.url), limit));
		}
		if (!files.length) throw new SRError('The model returned no image. Change the prompt and try again.');
		return files;
	}

	static refsFromChat(body: Record<string, unknown>): { refs: string[]; text: string } {
		const choice = Array.isArray(body.choices) && isRecord(body.choices[0]) ? body.choices[0] : {};
		const message = isRecord(choice.message) ? choice.message : {};
		const refs: string[] = [];
		const texts: string[] = [];
		const urlOf = (value: unknown) => (isRecord(value) ? value.url : value);
		const content = message.content;
		for (const part of Array.isArray(content) ? content : [content]) {
			if (typeof part === 'string') texts.push(part);
			else if (isRecord(part)) {
				if (part.type === 'text') texts.push(String(part.text ?? ''));
				const url = urlOf(part.image_url);
				if (url) refs.push(String(url));
			}
		}
		for (const extra of Array.isArray(message.images) ? message.images : []) {
			const url = isRecord(extra) ? urlOf(extra.image_url) : undefined;
			if (url) refs.push(String(url));
		}
		const text = texts.filter(Boolean).join('\n');
		let found = Array.from(text.matchAll(MD_IMAGE), (m) => m[1]);
		if (!found.length && !refs.length) {
			found = text.match(BARE_DATA) ?? text.match(BARE_LINK) ?? [];
		}
		return { refs: [...refs, ...found], text };
	}

	/** The native route, because some upstreams ignore size and ratio when asked in the OpenAI format. */
	private async geminiImage(model: string, prompt: string, options: ImageOptions, limit: number): Promise<GeneratedFile[]> {
		const parts: Array<Record<string, unknown>> = [{ text: prompt }];
		for (const image of options.images ?? []) {
			parts.push({ inlineData: { mimeType: image.mime, data: encodeBase64(image.data) } });
		}
		const generationConfig: Record<string, unknown> = { responseModalities: ['TEXT', 'IMAGE'] };
		const config: Record<string, string> = {};
		if (options.aspectRatio && options.aspectRatio !== 'auto') config.aspectRatio = options.aspectRatio;
		if (options.imageSize && options.imageSize !== 'auto') config.imageSize = options.imageSize;
		if (Object.keys(config).length) generationConfig.imageConfig = config;
		const body = await this.call('POST', `/v1beta/models/${encodeURIComponent(model)}:generateContent`, {
			json: { contents: [{ role: 'user', parts }], generationConfig },
			timeoutMs: IMAGE_TIMEOUT_MS,
		});
		const first = Array.isArray(body.candidates) && isRecord(body.candidates[0]) ? body.candidates[0] : {};
		const content = isRecord(first.content) ? first.content : {};
		const files: GeneratedFile[] = [];
		const texts: string[] = [];
		for (const part of Array.isArray(content.parts) ? content.parts : []) {
			if (!isRecord(part) || part.thought) continue; // the model's notes and drafts, not the result
			const inline = part.inlineData ?? part.inline_data;
			const linked = part.fileData ?? part.file_data;
			if (isRecord(inline) && inline.data) files.push(this.asImage(this.decode(String(inline.data)), limit));
			else if (isRecord(linked) && (linked.fileUri || linked.file_uri)) {
				files.push(await this.fileFromRef(String(linked.fileUri ?? linked.file_uri), limit));
			} else if (part.text) texts.push(String(part.text));
		}
		if (files.length) return files;
		const text = texts.join('\n');
		const marked = Array.from(text.matchAll(MD_IMAGE), (m) => m[1]);
		const refs = marked.length ? marked : text.match(BARE_DATA) ?? text.match(BARE_LINK) ?? [];
		if (!refs.length) throw new SRError(`The model returned no image. ${scrub(text || String(first.finishReason ?? ''), this.secret)}`.trim());
		for (const ref of refs) files.push(await this.fileFromRef(ref, limit));
		return files;
	}

	/** Only for reference links: the native route has no way to pass an arbitrary link, and fetching them here costs a Worker its CPU budget. */
	private async chatImage(model: string, prompt: string, options: ImageOptions, limit: number): Promise<GeneratedFile[]> {
		const content: Array<Record<string, unknown>> = [{ type: 'text', text: prompt }];
		for (const image of options.images ?? []) {
			content.push({ type: 'image_url', image_url: { url: `data:${image.mime};base64,${encodeBase64(image.data)}` } });
		}
		for (const url of options.imageUrls ?? []) content.push({ type: 'image_url', image_url: { url } });
		const payload: Record<string, unknown> = { model, stream: false, messages: [{ role: 'user', content }] };
		const config: Record<string, string> = {};
		if (options.aspectRatio && options.aspectRatio !== 'auto') config.aspect_ratio = options.aspectRatio;
		if (options.imageSize && options.imageSize !== 'auto') config.image_size = options.imageSize;
		if (Object.keys(config).length) payload.extra_body = { google: { image_config: config } };
		const body = await this.call('POST', '/v1/chat/completions', { json: payload, timeoutMs: IMAGE_TIMEOUT_MS });
		const { refs, text } = SRClient.refsFromChat(body);
		if (!refs.length) throw new SRError(`The model returned no image. ${scrub(text, this.secret)}`.trim());
		const files: GeneratedFile[] = [];
		for (const ref of refs) files.push(await this.fileFromRef(ref, limit));
		return files;
	}

	/** Text to image, or image edit when reference images are given. Always returns file bytes. */
	async generateImage(model: string, prompt: string, options: ImageOptions = {}): Promise<GeneratedFile[]> {
		if (!prompt || !prompt.trim()) throw new ValidationError('A prompt is required.');
		if (!model) throw new ValidationError('Choose a model.');
		const limit = options.limit ?? MAX_FILE_BYTES;
		if (matchesAny(model, gen.CHAT_IMAGE_MATCH)) {
			return options.imageUrls?.length ? this.chatImage(model, prompt, options, limit) : this.geminiImage(model, prompt, options, limit);
		}
		if (options.imageUrls?.length) throw new ValidationError('This model does not take reference image links.');
		const fields: Record<string, unknown> = { model, prompt, n: options.n ?? 1 };
		if (options.size && options.size !== 'auto') fields.size = options.size;
		if (options.quality && options.quality !== 'auto') fields.quality = options.quality;
		const images = options.images ?? [];
		let body: Record<string, unknown>;
		if (images.length) {
			const files = images.map((f, i) => ({ field: 'image[]', name: `image-${i}.${extensionOf(f.mime)}`, mime: f.mime, data: f.data }));
			const text = Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, String(v)]));
			body = await this.call('POST', '/v1/images/edits', { form: { fields: text, files }, timeoutMs: IMAGE_TIMEOUT_MS });
		} else {
			body = await this.call('POST', '/v1/images/generations', { json: fields, timeoutMs: IMAGE_TIMEOUT_MS });
		}
		return this.imagesFromReply(body, limit);
	}

	// ---- video ----

	/** Build the request, refusing values the gateway would refuse. Unlisted models pass through. */
	static videoPayload(model: string, prompt: string, options: VideoOptions = {}): Record<string, unknown> {
		if (!prompt || !prompt.trim()) throw new ValidationError('A prompt is required.');
		if (!model) throw new ValidationError('Choose a model.');
		const rule = gen.VIDEO_PARAMS[model];
		const payload: Record<string, unknown> = { model, prompt };
		const resolution = options.resolution ? options.resolution.toLowerCase() : undefined;
		const { seconds, startImage } = options;
		if (rule) {
			if (resolution && !rule.resolutions.includes(resolution)) {
				throw new ValidationError(`${model} takes these resolutions: ${rule.resolutions.join(', ')}.`);
			}
			const allowed = rule.seconds;
			if (seconds !== undefined) {
				if (allowed.values && !allowed.values.includes(seconds)) {
					throw new ValidationError(`${model} takes these lengths in seconds: ${allowed.values.join(', ')}.`);
				}
				if (allowed.min !== undefined && allowed.max !== undefined && !(allowed.min <= seconds && seconds <= allowed.max)) {
					throw new ValidationError(`${model} takes ${allowed.min} to ${allowed.max} seconds.`);
				}
			}
			if (rule.start_image === 'required' && !startImage) throw new ValidationError(`${model} needs a starting image.`);
			if (rule.start_image === 'none' && startImage) throw new ValidationError(`${model} does not take a starting image.`);
		}
		const style = rule ? rule.style : model.startsWith('doubao-seedance-') ? 'metadata' : 'top';
		if (style === 'metadata') {
			const meta: Record<string, unknown> = {};
			if (resolution !== undefined) meta.resolution = resolution;
			if (seconds !== undefined) meta.duration = seconds;
			if (Object.keys(meta).length) payload.metadata = meta;
		} else {
			if (resolution) payload.size = resolution;
			if (seconds !== undefined) payload.duration = seconds;
		}
		if (startImage) {
			const key = rule ? rule.image_key : model.startsWith('wan') ? 'image' : 'images';
			payload[key] = key === 'images' ? [startImage] : startImage;
		}
		return payload;
	}

	async submitVideo(model: string, prompt: string, options: VideoOptions = {}): Promise<string> {
		const payload = SRClient.videoPayload(model, prompt, options);
		const data = inner(await this.call('POST', '/v1/video/generations', { json: payload }));
		const taskId = data.task_id || data.id;
		if (!taskId) throw new SRError('SteadyRouter did not return a task ID.');
		return String(taskId);
	}

	async videoStatus(taskId: string): Promise<VideoStatus> {
		if (!taskId || !/^[A-Za-z0-9_.:-]+$/.test(taskId)) throw new ValidationError('That task ID does not look right.');
		const data = inner(await this.call('GET', `/v1/video/generations/${taskId}`));
		let status = String(data.status ?? '').toUpperCase();
		if (status === 'COMPLETED') status = 'SUCCESS';
		else if (status === 'FAILED') status = 'FAILURE';
		const resultUrl = String(data.result_url || data.url || '');
		if (resultUrl) this.resultUrls.set(taskId, resultUrl);
		return {
			taskId,
			status,
			progress: String(data.progress ?? ''),
			failReason: scrub(data.fail_reason, this.secret),
			done: status === 'SUCCESS',
			failed: status === 'FAILURE',
		};
	}

	/** Check until the task ends. Throws VideoStillRunning with the ID when the wait runs out. */
	async waitVideo(taskId: string): Promise<VideoStatus> {
		const deadline = this.t.now() + this.videoWaitSeconds * 1000;
		for (;;) {
			const state = await this.videoStatus(taskId);
			if (state.done) return state;
			if (state.failed) {
				throw new VideoFailed(
					`No video was made and the charge is refunded. ${state.failReason || 'The upstream did not make the video.'}`,
				);
			}
			if (this.t.now() >= deadline) {
				throw new VideoStillRunning('The video is not ready yet. Check it later with the task ID.', taskId);
			}
			await this.t.sleep(this.pollSeconds * 1000);
		}
	}

	/** Prefer the gateway's own download endpoint; the upstream link is only a fallback. */
	async downloadVideo(taskId: string, limit: number = MAX_VIDEO_BYTES): Promise<GeneratedFile> {
		if (!/^[A-Za-z0-9_.:-]+$/.test(taskId)) throw new ValidationError('That task ID does not look right.');
		let data: Uint8Array | undefined;
		const reply = await this.attempt({
			method: 'GET',
			url: `${this.baseUrl}/v1/videos/${taskId}/content`,
			auth: true,
			binary: true,
			maxBytes: limit,
			timeoutMs: DOWNLOAD_TIMEOUT_MS,
		});
		if ('failure' in reply) {
			if (reply.failure instanceof FileTooLarge) throw reply.failure;
		} else if (reply.status === 200) {
			data = this.capped(reply.bytes, limit);
		} else if (REDIRECTS.has(reply.status)) {
			// The gateway may send us to the file host: follow it without the key, through the same checks.
			const target = parseUrl(reply.headers.location ?? '', this.baseUrl + '/');
			if (target) data = await this.downloadPublic(target.toString(), limit).catch(() => undefined);
		}
		if (data === undefined) {
			const fallback = this.resultUrls.get(taskId);
			if (!fallback) throw new SRError('The video could not be downloaded.');
			data = await this.downloadPublic(fallback, limit);
		}
		const mime = sniff(data);
		if (!mime || !mime.startsWith('video/')) throw new SRError('The video could not be downloaded.');
		return { data, mime };
	}
}
