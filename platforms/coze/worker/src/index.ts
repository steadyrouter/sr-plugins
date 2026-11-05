// SteadyRouter's relay for Coze plugins (coze.com and coze.cn). Coze calls it with the user's own key in the
// Authorization header; it calls api.steadyrouter.com, stores the result in R2 and returns a link to it.
//
//   POST /coze/<region>/v1/images          generate an image
//   POST /coze/<region>/v1/videos          submit a video task
//   POST /coze/<region>/v1/videos/status   check it; once done, the video is stored and linked
//   GET  /<prefix><32 hex>.<ext>           a stored file (no listing)
//
// Rules: the key goes only to the gateway and is never logged; only links the
// gateway returns are downloaded (https, public hosts), never a link the caller sends; nothing is stored unless the
// gateway call succeeded; every reply is HTTP 200 JSON with `code` (0 = ok) and a message safe to show.

import {
	FileTooLarge,
	SRClient,
	SRError,
	ValidationError,
	classify,
	familyOf,
	generated,
	pricingModels,
	type ImageOptions,
	type PricingRow,
	type VideoOptions,
} from './srclient';
import { FetchTransport } from './transport';
import { findVideo, serveFile, storeFile, streamVideo, taskName } from './files';
import * as cfg from './config';

const PRICING_TTL_MS = 10 * 60 * 1000;
const KEY_RE = /^[A-Za-z0-9._-]{8,200}$/;
const TASK_RE = /^[A-Za-z0-9_.:-]{1,128}$/;

type Region = keyof typeof cfg.REGIONS;
type Payload = Record<string, unknown>;

class InputError extends ValidationError {}

// ---- model lists (per isolate, refreshed every 10 minutes) ----

let pricing: { at: number; rows: PricingRow[] } | null = null;

async function categoryOf(model: string): Promise<string | null> {
	if (!pricing || Date.now() - pricing.at > PRICING_TTL_MS) {
		try {
			pricing = { at: Date.now(), rows: await pricingModels(new FetchTransport(''), cfg.PRICING_URL) };
		} catch {
			pricing = null;
		}
	}
	if (pricing) {
		const row = pricing.rows.find((r) => r.model_name === model);
		return row ? classify(row, generated.CATEGORY_OVERRIDES) : null;
	}
	return generated.SHIPPED_MODELS.find((m) => m.name === model)?.category ?? null;
}

async function checkModel(region: Region, model: string, category: 'image' | 'video'): Promise<void> {
	if (!model) throw new InputError('Choose a model.');
	const families = cfg.REGIONS[region].families;
	const familyOk = families === 'all' || (families as readonly string[]).includes(familyOf(model, generated.FAMILIES) ?? '');
	if (!familyOk || (cfg.EXCLUDE as readonly string[]).includes(model) || (await categoryOf(model)) !== category) {
		throw new InputError(`${model} is not offered by this plugin. Pick a model from the list.`);
	}
}

// ---- input ----

function text(body: Payload, name: string, max = 200): string {
	const v = body[name];
	if (v === undefined || v === null) return '';
	if (typeof v !== 'string' && typeof v !== 'number') throw new InputError(`${name} must be text.`);
	const s = String(v).trim();
	if (s.length > max) throw new InputError(`${name} is too long.`);
	return s;
}

function option(body: Payload, name: string): string | undefined {
	const v = text(body, name);
	return v && v !== 'auto' ? v : undefined;
}

function link(value: unknown, name: string): string {
	if (typeof value !== 'string' || value.length > 2048) throw new InputError(`${name} must be a link.`);
	let url: URL;
	try {
		url = new URL(value.trim());
	} catch {
		throw new InputError(`${name} must be a link.`);
	}
	if (url.protocol !== 'https:') throw new InputError(`${name} must be an https link.`);
	return url.toString();
}

function links(body: Payload, name: string): string[] {
	const v = body[name];
	if (v === undefined || v === null || v === '') return [];
	const list = Array.isArray(v) ? v : [v];
	if (list.length > cfg.LIMITS.reference_images) throw new InputError(`Up to ${cfg.LIMITS.reference_images} ${name}.`);
	return list.filter((x) => x !== '').map((x) => link(x, name));
}

function prompt(body: Payload): string {
	const p = text(body, 'prompt', cfg.LIMITS.prompt_chars);
	if (!p) throw new InputError('A prompt is required.');
	return p;
}

function bearer(request: Request): string {
	const raw = (request.headers.get('authorization') ?? '').trim();
	const key = raw.replace(/^bearer\s+/i, '').trim();
	if (!KEY_RE.test(key)) {
		throw new SRError(
			'Add your SteadyRouter API key: bind the Authorization parameter to a private variable whose value is "Bearer <your key>".',
			{ status: 401 },
		);
	}
	return key;
}

async function readBody(request: Request): Promise<Payload> {
	const limit = cfg.LIMITS.request_kb * 1024;
	if (Number(request.headers.get('content-length')) > limit) throw new InputError('The request is too large.');
	const raw = await request.text();
	if (raw.length > limit) throw new InputError('The request is too large.');
	let body: unknown;
	try {
		body = raw ? JSON.parse(raw) : {};
	} catch {
		throw new InputError('The request body must be JSON.');
	}
	if (typeof body !== 'object' || body === null || Array.isArray(body)) throw new InputError('The request body must be a JSON object.');
	return body as Payload;
}

// ---- replies ----

const ZH: Record<string, string> = {
	'A prompt is required.': '请填写提示词。',
	'Choose a model.': '请选择型号。',
	'The API key is wrong, disabled, expired or out of its spending cap.': 'API Key 不对、已停用、已过期，或者到了它的额度上限。',
	'Your SteadyRouter balance cannot cover this request. Add funds and try again.': 'SteadyRouter 余额不够这次请求，充值后再试。',
	'Your SteadyRouter balance cannot cover this request, or this key may not use this model.': 'SteadyRouter 余额不够，或者这个 Key 不能用这个型号。',
	'The model name is wrong, or the groups your API key uses do not offer this model.': '型号名不对，或者这个 Key 的分组里没有这个型号。',
	'The service is busy. Try again in a little while.': '服务繁忙，请稍后再试。',
	'The request timed out. Try again in a little while.': '请求超时，请稍后再试。',
	'Could not reach SteadyRouter. Check the network and try again.': '连不上 SteadyRouter，请稍后再试。',
	'The file is larger than the size limit.': '文件超过大小上限。',
	'The video is larger than the size limit.': '视频超过大小上限。',
	'The model returned no image. Change the prompt and try again.': '型号没有返回图片，换个提示词再试。',
	'Add your SteadyRouter API key: bind the Authorization parameter to a private variable whose value is "Bearer <your key>".':
		'请填写 SteadyRouter API Key：把 Authorization 参数用「引用」绑定到一个私有变量，变量值写 Bearer 加你的 Key。',
	'The video is not ready yet.': '视频还在生成，稍后用同一个任务 ID 再查。',
	'No video was made and the charge is refunded.': '视频没有生成，费用已退回。',
	'Something went wrong on our side. Try again in a little while.': '服务出错了，请稍后再试。',
};

function say(region: Region, message: string): string {
	return cfg.REGIONS[region].lang === 'zh' ? (ZH[message] ?? message) : message;
}

function reply(payload: Payload, status = 200): Response {
	return Response.json(payload, { status, headers: { 'Cache-Control': 'no-store' } });
}

function failure(region: Region, err: unknown, key: string, empty: Payload): Response {
	let code = 500;
	let msg = 'Something went wrong on our side. Try again in a little while.';
	if (err instanceof ValidationError) {
		code = 400;
		msg = err.message;
	} else if (err instanceof FileTooLarge) {
		code = 413;
		msg = err.message;
	} else if (err instanceof SRError) {
		code = err.status ?? 502;
		msg = err.message;
	}
	// Gateway text was already scrubbed by the client; our own messages mention "Bearer <your key>", which a full
	// scrub would mangle, so only the caller's actual key is removed here.
	const text = say(region, msg);
	return reply({ ...empty, code, msg: key ? text.split(key).join('[key removed]') : text });
}

// ---- tools ----

const IMAGE_EMPTY = { image_url: '', image_urls: [], model: '', expires_in_days: cfg.KEEP_DAYS };
const SUBMIT_EMPTY = { task_id: '', status: '' };
const STATUS_EMPTY = { task_id: '', status: '', progress: '', video_url: '', fail_reason: '', expires_in_days: cfg.KEEP_DAYS };

function client(transport: FetchTransport, key: string): SRClient {
	return new SRClient(transport, {
		baseUrl: cfg.API_BASE,
		secret: key,
		decode: transport.decode,
		httpsOnly: !cfg.TEST_BUILD,
		...(cfg.TEST_BUILD ? { checkHost: () => undefined } : {}),
	});
}

async function image(region: Region, body: Payload, key: string, env: Env): Promise<Payload> {
	const model = text(body, 'model');
	const p = prompt(body);
	await checkModel(region, model, 'image');
	const options: ImageOptions = {
		size: option(body, 'size'),
		quality: option(body, 'quality'),
		aspectRatio: option(body, 'aspect_ratio'),
		imageSize: option(body, 'image_size'),
		imageUrls: links(body, 'reference_images'),
		limit: cfg.LIMITS.image_mb * 1024 * 1024,
	};
	const transport = new FetchTransport(key);
	const files = await client(transport, key).generateImage(model, p, options);
	const urls: string[] = [];
	for (const file of files) urls.push(await storeFile(env, file, region));
	return { ...IMAGE_EMPTY, code: 0, msg: '', image_url: urls[0], image_urls: urls, model };
}

async function submit(region: Region, body: Payload, key: string): Promise<Payload> {
	const model = text(body, 'model');
	const p = prompt(body);
	await checkModel(region, model, 'video');
	const seconds = text(body, 'seconds');
	if (seconds && !/^\d{1,3}$/.test(seconds)) throw new InputError('seconds must be a whole number.');
	const start = body.start_image ? link(body.start_image, 'start_image') : undefined;
	const options: VideoOptions = { resolution: option(body, 'resolution'), seconds: seconds ? Number(seconds) : undefined, startImage: start };
	const transport = new FetchTransport(key);
	const taskId = await client(transport, key).submitVideo(model, p, options);
	return { ...SUBMIT_EMPTY, code: 0, msg: '', task_id: taskId, status: 'queued' };
}

async function status(region: Region, body: Payload, key: string, env: Env): Promise<Payload> {
	const taskId = text(body, 'task_id', 128);
	if (!TASK_RE.test(taskId)) throw new InputError('That task ID does not look right.');
	if (!env.FILE_NAME_SECRET) throw new Error('FILE_NAME_SECRET is not set');
	const transport = new FetchTransport(key);
	const sr = client(transport, key);
	const state = await sr.videoStatus(taskId); // the gateway checks the task belongs to this key
	const base = { ...STATUS_EMPTY, code: 0, msg: '', task_id: taskId, progress: state.progress };
	if (state.failed) {
		return { ...base, status: 'failed', msg: say(region, 'No video was made and the charge is refunded.'), fail_reason: state.failReason };
	}
	if (!state.done) return { ...base, status: 'running', msg: say(region, 'The video is not ready yet.') };
	const name = await taskName(env.FILE_NAME_SECRET, taskId);
	let url = (await findVideo(env, name)) ?? (await streamVideo(env, key, taskId, name, region));
	if (!url) {
		const file = await sr.downloadVideo(taskId, cfg.LIMITS.video_buffer_mb * 1024 * 1024);
		const ext = file.mime === 'video/webm' ? 'webm' : 'mp4';
		await env.FILES.put(`${cfg.PREFIX}${name}.${ext}`, file.data, { httpMetadata: { contentType: file.mime }, customMetadata: { region } });
		url = (await findVideo(env, name)) as string;
	}
	return { ...base, status: 'succeeded', progress: '100%', video_url: url };
}

// ---- routing ----

const ROUTES: Record<string, { empty: Payload; run: (region: Region, body: Payload, key: string, env: Env) => Promise<Payload> }> = {
	'v1/images': { empty: IMAGE_EMPTY, run: image },
	'v1/videos': { empty: SUBMIT_EMPTY, run: (r, b, k) => submit(r, b, k) },
	'v1/videos/status': { empty: STATUS_EMPTY, run: status },
};
const TOOL_PATH = /^\/coze\/([a-z]+)\/(v1\/images|v1\/videos|v1\/videos\/status)$/;

export default {
	async fetch(request: Request, env: Env): Promise<Response> {
		const path = new URL(request.url).pathname;
		const tool = TOOL_PATH.exec(path);
		if (!tool) {
			if (request.method === 'GET' || request.method === 'HEAD') return serveFile(env, request, path);
			return new Response('Not found', { status: 404 });
		}
		const region = tool[1] as Region;
		if (!(region in cfg.REGIONS)) return new Response('Not found', { status: 404 });
		if (request.method !== 'POST') return new Response('Method not allowed', { status: 405, headers: { Allow: 'POST' } });
		const route = ROUTES[tool[2]];
		let key = '';
		try {
			key = bearer(request);
			const body = await readBody(request);
			return reply(await route.run(region, body, key, env));
		} catch (err) {
			return failure(region, err, key, route.empty);
		}
	},
};
