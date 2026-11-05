// srclient transport on top of fetch, for one request from Coze. Holds that caller's key; never logs anything.
//
// CPU matters here (the Workers Free plan allows 10 ms per request). An image reply can carry megabytes of base64,
// and JSON.parse plus a regex over it costs more than the decoding itself. So before parsing, long base64 runs are
// cut out ("lifted") and replaced by a short placeholder; decode() turns the placeholder back into bytes with the
// runtime's native Uint8Array.fromBase64.

import { FileTooLarge, TransportError, tryDecodeBase64, type HttpReply, type HttpRequest, type Transport } from './srclient';

const JSON_MAX_BYTES = 40 * 1024 * 1024;
const LIFT_FROM = 64 * 1024; // only bodies this large are worth lifting
const RUN_MIN = 4096; // shorter base64 runs stay in place
const PLACEHOLDER = /^__srlift_(\d+)__$/;

/** Read a body, refusing more than `limit` bytes (by Content-Length up front, then while reading). */
export async function readCapped(res: Response, limit: number): Promise<Uint8Array> {
	const declared = Number(res.headers.get('content-length'));
	if (Number.isFinite(declared) && declared > limit) {
		await res.body?.cancel();
		throw new FileTooLarge('The file is larger than the size limit.', limit);
	}
	if (!res.body) return new Uint8Array();
	const reader = res.body.getReader();
	const chunks: Uint8Array[] = [];
	let total = 0;
	for (;;) {
		const { done, value } = await reader.read();
		if (done) break;
		total += value.length;
		if (total > limit) {
			await reader.cancel();
			throw new FileTooLarge('The file is larger than the size limit.', limit);
		}
		chunks.push(value);
	}
	if (chunks.length === 1) return chunks[0];
	const out = new Uint8Array(total);
	let at = 0;
	for (const c of chunks) {
		out.set(c, at);
		at += c.length;
	}
	return out;
}

export function nativeDecode(text: string): Uint8Array | null {
	const native = Uint8Array.fromBase64;
	if (native) {
		for (const alphabet of ['base64', 'base64url'] as const) {
			try {
				return native(text, { alphabet });
			} catch {
				// try the other alphabet, then the portable decoder
			}
		}
	}
	return tryDecodeBase64(text);
}

export class FetchTransport implements Transport {
	private readonly lifted: string[] = [];

	constructor(private readonly key: string) {}

	async request(req: HttpRequest): Promise<HttpReply> {
		const headers = new Headers({ Accept: req.binary ? '*/*' : 'application/json' });
		if (req.auth) headers.set('Authorization', `Bearer ${this.key}`);
		let body: BodyInit | undefined;
		if (req.json !== undefined) {
			headers.set('Content-Type', 'application/json');
			body = JSON.stringify(req.json);
		} else if (req.form) {
			const form = new FormData();
			for (const [k, v] of Object.entries(req.form.fields)) form.append(k, v);
			for (const f of req.form.files) form.append(f.field, new Blob([f.data as Uint8Array<ArrayBuffer>], { type: f.mime }), f.name);
			body = form;
		}
		let res: Response;
		try {
			res = await fetch(req.url, {
				method: req.method,
				headers,
				body,
				redirect: 'manual',
				signal: AbortSignal.timeout(req.timeoutMs),
			});
		} catch (err) {
			const name = (err as { name?: string })?.name;
			const timeout = name === 'TimeoutError' || name === 'AbortError';
			throw new TransportError(timeout ? 'timed out' : 'request failed', timeout);
		}
		const replyHeaders = {
			location: res.headers.get('location') ?? undefined,
			'content-type': res.headers.get('content-type') ?? undefined,
		};
		if (req.binary) {
			return { status: res.status, headers: replyHeaders, bytes: await readCapped(res, req.maxBytes ?? JSON_MAX_BYTES) };
		}
		const bytes = await readCapped(res, JSON_MAX_BYTES);
		return { status: res.status, headers: replyHeaders, body: this.parse(new TextDecoder().decode(bytes)) };
	}

	sleep(ms: number): Promise<void> {
		return new Promise((resolve) => setTimeout(resolve, ms));
	}

	now(): number {
		return Date.now();
	}

	/** For SRClient's `decode` option: resolves placeholders, then decodes natively. */
	readonly decode = (text: string): Uint8Array | null => {
		const m = PLACEHOLDER.exec(text);
		if (m) {
			const run = this.lifted[Number(m[1])];
			return run === undefined ? null : nativeDecode(run);
		}
		return nativeDecode(text);
	};

	private parse(text: string): unknown {
		try {
			return JSON.parse(text.length >= LIFT_FROM ? this.lift(text) : text);
		} catch {
			return undefined;
		}
	}

	/**
	 * Swap long base64 runs for placeholders made of base64-safe characters, so the client's link and data-URI
	 * patterns still match them. A run starts after `"b64_json":"` or `;base64,` and ends at the next `"` or `)`.
	 * Runs that hold a backslash (a JSON escape) stay in place and go through the normal parser.
	 */
	lift(text: string): string {
		let out = '';
		let pos = 0;
		for (;;) {
			const a = text.indexOf('"b64_json":"', pos);
			const b = text.indexOf(';base64,', pos);
			let start: number;
			if (a >= 0 && (b < 0 || a < b)) start = a + 12;
			else if (b >= 0) start = b + 8;
			else break;
			const quote = text.indexOf('"', start);
			const paren = text.indexOf(')', start);
			const end = quote < 0 ? paren : paren < 0 ? quote : Math.min(quote, paren);
			if (end < 0) break;
			const run = text.slice(start, end);
			if (run.length < RUN_MIN || run.includes('\\')) {
				out += text.slice(pos, end);
			} else {
				out += `${text.slice(pos, start)}__srlift_${this.lifted.length}__`;
				this.lifted.push(run);
			}
			pos = end;
		}
		return out + text.slice(pos);
	}
}
