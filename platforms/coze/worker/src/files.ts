// Generated files in R2: naming, storing, serving. Only `<prefix><32 hex>.<allowed extension>` is ever read or written.

import { FileTooLarge, SRError, literalHostCheck, sniff, type GeneratedFile } from './srclient';
import { readCapped } from './transport';
import * as cfg from './config';

/** Extension → Content-Type. Nothing outside this list is stored or served. */
export const TYPES: Record<string, string> = {
	png: 'image/png',
	jpg: 'image/jpeg',
	webp: 'image/webp',
	gif: 'image/gif',
	mp4: 'video/mp4',
	webm: 'video/webm',
};
const EXT_OF: Record<string, string> = Object.fromEntries(Object.entries(TYPES).map(([ext, mime]) => [mime, ext]));
const FILE_PATH = new RegExp(`^/${cfg.PREFIX}([0-9a-f]{32})\\.(${Object.keys(TYPES).join('|')})$`);
const MAX_REDIRECTS = 3;
const REDIRECTS = new Set([301, 302, 303, 307, 308]);
const DOWNLOAD_TIMEOUT_MS = 300_000;

function hex(bytes: Uint8Array): string {
	return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function randomName(): string {
	return hex(crypto.getRandomValues(new Uint8Array(16)));
}

/** Same task → same name, unguessable without the secret, so a repeated status check reuses the stored video. */
export async function taskName(secret: string, taskId: string): Promise<string> {
	const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, [
		'sign',
	]);
	const mac = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`video:${taskId}`));
	return hex(new Uint8Array(mac)).slice(0, 32);
}

export function publicUrl(env: Env, name: string, ext: string): string {
	return `${env.FILES_BASE_URL.replace(/\/+$/, '')}/${cfg.PREFIX}${name}.${ext}`;
}

export async function storeFile(env: Env, file: GeneratedFile, region: string): Promise<string> {
	const ext = EXT_OF[file.mime];
	if (!ext) throw new SRError('The model returned a file type this plugin does not handle.');
	const name = randomName();
	await env.FILES.put(`${cfg.PREFIX}${name}.${ext}`, file.data, {
		httpMetadata: { contentType: file.mime },
		customMetadata: { region },
	});
	return publicUrl(env, name, ext);
}

/** A stored video for this task, if an earlier check already saved it. */
export async function findVideo(env: Env, name: string): Promise<string | null> {
	for (const ext of ['mp4', 'webm']) {
		if (await env.FILES.head(`${cfg.PREFIX}${name}.${ext}`)) return publicUrl(env, name, ext);
	}
	return null;
}

async function checkLink(url: string): Promise<void> {
	let parts: URL;
	try {
		parts = new URL(url);
	} catch {
		throw new SRError('The video could not be downloaded.');
	}
	if (parts.protocol !== 'https:' && !(cfg.TEST_BUILD && parts.protocol === 'http:')) {
		throw new SRError('The video could not be downloaded.');
	}
	if (!cfg.TEST_BUILD) literalHostCheck(parts.hostname);
}

/**
 * Fetch the video from the gateway's own download endpoint (with the caller's key) and stream it into R2.
 * A redirect from the gateway is followed without the key, https only, to public hosts. Returns null when the
 * gateway has no file to give, so the caller can fall back to the client's buffered download.
 */
export async function streamVideo(env: Env, key: string, taskId: string, name: string, region: string): Promise<string | null> {
	let target = `${cfg.API_BASE}/v1/videos/${encodeURIComponent(taskId)}/content`;
	let auth = true;
	for (let hop = 0; hop <= MAX_REDIRECTS; hop++) {
		if (!auth) await checkLink(target);
		let res: Response;
		try {
			res = await fetch(target, {
				headers: auth ? { Authorization: `Bearer ${key}` } : {},
				redirect: 'manual',
				signal: AbortSignal.timeout(DOWNLOAD_TIMEOUT_MS),
			});
		} catch {
			return null;
		}
		if (REDIRECTS.has(res.status)) {
			const next = res.headers.get('location');
			await res.body?.cancel();
			if (!next) return null;
			target = new URL(next, target).toString();
			auth = false;
			continue;
		}
		if (res.status !== 200 || !res.body) {
			await res.body?.cancel();
			return null;
		}
		return putVideo(env, res, name, region);
	}
	return null;
}

async function putVideo(env: Env, res: Response, name: string, region: string): Promise<string> {
	const limit = cfg.LIMITS.video_mb * 1024 * 1024;
	const length = Number(res.headers.get('content-length'));
	if (!Number.isFinite(length) || length <= 0) {
		// No length: buffer it (bounded), sniff it, store it.
		const data = await readCapped(res, cfg.LIMITS.video_buffer_mb * 1024 * 1024);
		const mime = sniff(data);
		if (!mime || !mime.startsWith('video/')) throw new SRError('The video could not be downloaded.');
		await env.FILES.put(`${cfg.PREFIX}${name}.${EXT_OF[mime]}`, data, { httpMetadata: { contentType: mime }, customMetadata: { region } });
		return publicUrl(env, name, EXT_OF[mime]);
	}
	if (length > limit) {
		await res.body?.cancel();
		throw new FileTooLarge('The video is larger than the size limit.', limit);
	}
	const reader = (res.body as ReadableStream<Uint8Array>).getReader();
	const head: Uint8Array[] = [];
	let got = 0;
	while (got < 16) {
		const { done, value } = await reader.read();
		if (done) break;
		head.push(value);
		got += value.length;
	}
	const first = new Uint8Array(got);
	let at = 0;
	for (const c of head) {
		first.set(c, at);
		at += c.length;
	}
	const mime = sniff(first);
	if (!mime || !mime.startsWith('video/')) {
		await reader.cancel();
		throw new SRError('The video could not be downloaded.');
	}
	const pipe = new FixedLengthStream(length);
	const writer = pipe.writable.getWriter();
	const pump = (async () => {
		await writer.write(first);
		for (;;) {
			const { done, value } = await reader.read();
			if (done) break;
			await writer.write(value);
		}
		await writer.close();
	})();
	const key = `${cfg.PREFIX}${name}.${EXT_OF[mime]}`;
	await Promise.all([env.FILES.put(key, pipe.readable, { httpMetadata: { contentType: mime }, customMetadata: { region } }), pump]);
	return publicUrl(env, name, EXT_OF[mime]);
}

/** GET / HEAD `/<prefix><32 hex>.<ext>`. Anything else is 404; there is no listing. */
export async function serveFile(env: Env, request: Request, path: string): Promise<Response> {
	const m = FILE_PATH.exec(path);
	if (!m) return new Response('Not found', { status: 404 });
	const object = await env.FILES.get(`${cfg.PREFIX}${m[1]}.${m[2]}`, { range: request.headers });
	if (!object) return new Response('Not found', { status: 404 });
	const headers = new Headers({
		'Content-Type': TYPES[m[2]],
		'Cache-Control': 'public, max-age=86400',
		'Accept-Ranges': 'bytes',
		'X-Content-Type-Options': 'nosniff',
		'Content-Security-Policy': "default-src 'none'; sandbox",
	});
	let status = 200;
	const r = object.range;
	if (r && request.headers.has('range')) {
		const offset = r.offset ?? (r.suffix !== undefined ? object.size - r.suffix : 0);
		const length = r.length ?? (r.suffix ?? object.size - offset);
		headers.set('Content-Range', `bytes ${offset}-${offset + length - 1}/${object.size}`);
		headers.set('Content-Length', String(length));
		status = 206;
	} else {
		headers.set('Content-Length', String(object.size));
	}
	if (request.method === 'HEAD') {
		await object.body.cancel();
		return new Response(null, { status, headers });
	}
	return new Response(object.body, { status, headers });
}
