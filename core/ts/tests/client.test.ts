// The TS client against the Python fake gateway (tests/fake_upstream.py). Run by tests/test_ts_client.py,
// which starts the fake and passes its address in FAKE_BASE. Same cases as tests/test_client.py.
import assert from 'node:assert/strict';
import { beforeEach, describe, test } from 'node:test';

import {
	FileTooLarge,
	SRClient,
	SRError,
	TransportError,
	ValidationError,
	VideoFailed,
	VideoStillRunning,
	listModels,
	literalHostCheck,
	pricingModels,
	scrub,
	videoDownloadHint,
	type ClientOptions,
	type HttpReply,
	type HttpRequest,
	type Transport,
} from '../srclient';

const BASE = process.env.FAKE_BASE ?? '';
const KEY = process.env.FAKE_KEY ?? '';
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...new Array(64).fill(0)]);
const MP4 = new Uint8Array([0, 0, 0, 0x18, ...Array.from('ftypmp42', (c) => c.charCodeAt(0)), ...new Array(64).fill(0)]);

interface Seen {
	method: string;
	path: string;
	auth: string | null;
	ctype: string;
	body: unknown;
}

function fetchTransport(key: string = KEY): Transport {
	return {
		async request(req: HttpRequest): Promise<HttpReply> {
			const headers: Record<string, string> = {};
			if (req.auth) headers.Authorization = `Bearer ${key}`;
			let body: string | FormData | undefined;
			if (req.json !== undefined) {
				headers['Content-Type'] = 'application/json';
				body = JSON.stringify(req.json);
			} else if (req.form) {
				const form = new FormData();
				for (const [k, v] of Object.entries(req.form.fields)) form.append(k, v);
				for (const f of req.form.files) form.append(f.field, new Blob([f.data], { type: f.mime }), f.name);
				body = form;
			}
			let reply: Response;
			try {
				reply = await fetch(req.url, {
					method: req.method,
					headers,
					body,
					redirect: 'manual',
					signal: AbortSignal.timeout(req.timeoutMs),
				});
			} catch (err) {
				throw new TransportError(String(err), (err as Error).name === 'TimeoutError');
			}
			const bytes = new Uint8Array(await reply.arrayBuffer());
			if (req.maxBytes && bytes.length > req.maxBytes) throw new FileTooLarge('too large', req.maxBytes);
			const out: HttpReply = { status: reply.status, headers: Object.fromEntries(reply.headers) };
			if (req.binary) out.bytes = bytes;
			else {
				try {
					out.body = JSON.parse(new TextDecoder().decode(bytes));
				} catch {
					out.body = undefined;
				}
			}
			return out;
		},
		sleep: async () => undefined,
		now: () => Date.now(),
	};
}

function client(options: ClientOptions = {}, key: string = KEY): SRClient {
	return new SRClient(fetchTransport(key), {
		baseUrl: BASE,
		secret: key,
		checkHost: () => undefined,
		httpsOnly: false,
		pollSeconds: 0,
		videoWaitSeconds: 5,
		...options,
	});
}

async function seen(prefix = ''): Promise<Seen[]> {
	const all = (await (await fetch(`${BASE}/__seen`)).json()) as Seen[];
	return all.filter((r) => r.path.startsWith(prefix));
}

function assertClean(text: string): void {
	assert.ok(!text.includes(KEY), text);
	assert.ok(!text.includes('http://') && !text.includes('https://'), text);
	assert.ok(!text.includes('org-private-account'), text);
}

async function rejects(promise: Promise<unknown>, type: new (...args: never[]) => Error, match?: RegExp): Promise<Error> {
	try {
		await promise;
	} catch (err) {
		assert.ok(err instanceof type, `expected ${type.name}, got ${String(err)}`);
		if (match) assert.match((err as Error).message, match);
		return err as Error;
	}
	assert.fail(`expected ${type.name}`);
}

beforeEach(async () => {
	await fetch(`${BASE}/__reset`);
});

describe('images', () => {
	test('b64 reply', async () => {
		assert.deepEqual((await client().generateImage('m-b64', 'cat'))[0].data, PNG);
	});

	test('url reply is downloaded without the key', async () => {
		const files = await client().generateImage('m-url', 'cat');
		assert.deepEqual(files[0].data, PNG);
		assert.equal(files[0].mime, 'image/png');
		assert.equal((await seen('/upstream/org-private-account'))[0].auth, null);
	});

	for (const model of ['gemini-inline-image', 'gemini-snake-image', 'gemini-thought-image', 'gemini-file-image', 'gemini-md-data-image', 'gemini-md-link-image', 'gemini-bare-image']) {
		test(`gemini image shape ${model}`, async () => {
			const files = await client().generateImage(model, 'cat');
			assert.equal(files.length, 1); // the thought draft is never returned
			assert.deepEqual(files[0].data, PNG);
			assert.ok((await seen(`/v1beta/models/${model}:generateContent`)).length);
			assert.equal((await seen('/v1/chat/completions')).length, 0);
		});
	}

	test('gemini image sends size, ratio and references natively', async () => {
		await client().generateImage('gemini-inline-image', 'cat', { aspectRatio: '16:9', imageSize: '2K', images: [{ data: PNG, mime: 'image/png' }] });
		const body = (await seen('/v1beta/models/gemini-inline-image:generateContent'))[0].body as any;
		assert.deepEqual(body.generationConfig.imageConfig, { aspectRatio: '16:9', imageSize: '2K' });
		assert.deepEqual(body.generationConfig.responseModalities, ['TEXT', 'IMAGE']);
		assert.equal(body.contents[0].parts[0].text, 'cat');
		assert.equal(body.contents[0].parts[1].inlineData.mimeType, 'image/png');
		assert.ok(!('extra_body' in body));
	});

	test('gemini image auto sends no config', async () => {
		await client().generateImage('gemini-inline-image', 'cat', { aspectRatio: 'auto', imageSize: 'auto' });
		assert.ok(!('imageConfig' in ((await seen('/v1beta/models/'))[0].body as any).generationConfig));
	});

	test('blocked gemini reply says why', async () => {
		await rejects(client().generateImage('gemini-blocked-image', 'cat'), SRError, /IMAGE_SAFETY/);
	});

	for (const model of ['gemini-md-data-image', 'gemini-md-link-image', 'gemini-bare-image', 'gemini-parts-image', 'gemini-images-image']) {
		test(`reference links go through chat ${model}`, async () => {
			const out = await client().generateImage(model, 'cat', { imageUrls: ['https://images.example/a.png'], aspectRatio: '16:9', imageSize: '2K' });
			assert.deepEqual(out[0].data, PNG);
			const body = (await seen('/v1/chat/completions'))[0].body as any;
			assert.deepEqual(body.extra_body, { google: { image_config: { aspect_ratio: '16:9', image_size: '2K' } } });
			assert.deepEqual(body.messages[0].content[1], { type: 'image_url', image_url: { url: 'https://images.example/a.png' } });
			assert.equal((await seen('/v1beta/')).length, 0);
		});
	}

	for (const model of ['gemini-text-image', 'gemini-badlink-image', 'gemini-thoughts-only-image']) {
		test(`chat text reply is a clean error ${model}`, async () => {
			const err = await rejects(client().generateImage(model, 'cat'), SRError);
			assertClean(err.message);
		});
	}

	test('edit uses multipart', async () => {
		const files = await client().generateImage('m-b64', 'cat', { images: [{ data: PNG, mime: 'image/png' }] });
		assert.deepEqual(files[0].data, PNG);
		assert.match((await seen('/v1/images/edits'))[0].ctype, /multipart\/form-data/);
	});

	test('no image in reply', async () => {
		await rejects(client().generateImage('m-empty', 'cat'), SRError, /no image/);
	});

	test('non-image download is refused', async () => {
		await rejects(client().generateImage('m-url-html', 'cat'), SRError, /could not be read/);
	});

	test('oversize download stops', async () => {
		await rejects(client().generateImage('m-url-huge', 'cat', { limit: 1024 }), FileTooLarge);
	});

	test('empty prompt sends nothing', async () => {
		await rejects(client().generateImage('m-b64', '  '), ValidationError);
		assert.equal((await seen()).length, 0);
	});
});

describe('download safety', () => {
	test('http link refused by default', async () => {
		await rejects(client({ httpsOnly: true }).generateImage('m-url', 'cat'), SRError, /could not be downloaded/);
	});

	test('private address refused by default', async () => {
		const c = new SRClient(fetchTransport(), { baseUrl: BASE, httpsOnly: false });
		await rejects(c.generateImage('m-url', 'cat'), SRError, /could not be downloaded/);
	});

	const hosts: Array<[string, boolean]> = [
		['198.18.0.40', true], ['93.184.216.34', true], ['example.com', true], ['[2606:4700::1]', true],
		['127.0.0.1', false], ['10.0.0.5', false], ['192.168.1.1', false], ['172.17.0.2', false],
		['169.254.169.254', false], ['100.64.0.1', false], ['0.0.0.0', false], ['localhost', false],
		['db.internal', false], ['[::1]', false], ['[fd00::1]', false], ['[::ffff:127.0.0.1]', false],
	];
	for (const [host, allowed] of hosts) {
		test(`literal host check ${host}`, () => {
			const hostname = new URL(`https://${host}/x`).hostname;
			if (allowed) literalHostCheck(hostname);
			else assert.throws(() => literalHostCheck(hostname), SRError);
		});
	}

	test('numeric IPv4 spellings are normalised before the check', () => {
		for (const spelling of ['2130706433', '0x7f.1', '0177.0.0.1']) {
			assert.throws(() => literalHostCheck(new URL(`https://${spelling}/x`).hostname), SRError);
		}
	});

	test('each redirect hop is checked', async () => {
		const checked: string[] = [];
		await rejects(client({ checkHost: (h) => void checked.push(h) }).generateImage('m-url-http-redirect', 'cat'), SRError);
		assert.equal(checked.length, 2);
	});
});

describe('errors never carry a key or a link', () => {
	const cases: Array<[string, RegExp]> = [
		['err-429', /busy/], ['err-quota', /balance/], ['no-such-model', /groups your API key/], ['err-leak', /418/],
	];
	for (const [model, needle] of cases) {
		test(model, async () => {
			const err = await rejects(client().generateImage(model, 'cat'), SRError, needle);
			assertClean(err.message);
		});
	}

	test('wrong key', async () => {
		const err = (await rejects(client({}, 'sk-wrong-key-000000').generateImage('m-b64', 'cat'), SRError, /API key/)) as SRError;
		assert.equal(err.status, 401);
	});

	test('unreachable gateway', async () => {
		await rejects(new SRClient(fetchTransport(), { baseUrl: 'http://127.0.0.1:1' }).checkKey(), SRError, /Could not reach/);
	});

	test('scrub', () => {
		assertClean(scrub(`Bearer ${KEY} token-abcdefgh sk-abcdefgh https://a.example/b?c=d ${KEY}`, KEY));
		assert.equal(scrub('x'.repeat(5000)).length, 300);
		assert.equal(scrub(`see https://a.example/b?k=${KEY} now`, KEY), 'see [link removed] now');
	});
});

describe('chat', () => {
	test('plain reply', async () => {
		const out = await client().chat('some-chat', [{ role: 'user', content: 'hi' }], { temperature: 0.2, maxTokens: 50, jsonOutput: true });
		assert.equal(out.text, 'Hello');
		assert.equal(out.finishReason, 'stop');
		const body = (await seen('/v1/chat/completions'))[0].body as Record<string, unknown>;
		assert.equal(body.stream, false);
		assert.equal(body.max_completion_tokens, 50);
		assert.deepEqual(body.response_format, { type: 'json_object' });
	});

	test('no model sends nothing', async () => {
		await rejects(client().chat('', [{ role: 'user', content: 'hi' }]), ValidationError);
		assert.equal((await seen()).length, 0);
	});

	test('check key', async () => {
		await client().checkKey();
		await rejects(client({}, 'sk-wrong-key-000000').checkKey(), SRError, /API key/);
	});
});

describe('video', () => {
	test('payload top level', () => {
		assert.deepEqual(SRClient.videoPayload('viduq3-turbo', 'p', { resolution: '540P', seconds: 5 }), {
			model: 'viduq3-turbo', prompt: 'p', size: '540p', duration: 5,
		});
	});

	test('payload metadata', () => {
		const body = SRClient.videoPayload('doubao-seedance-2-0-mini-260615', 'p', { resolution: '480p', seconds: 4 });
		assert.deepEqual(body.metadata, { resolution: '480p', duration: 4 });
		assert.ok(!('size' in body));
	});

	test('payload start image keys', () => {
		assert.deepEqual(SRClient.videoPayload('viduq2-pro', 'p', { startImage: 'u' }).images, ['u']);
		assert.equal(SRClient.videoPayload('wan2.6-i2v', 'p', { startImage: 'u' }).image, 'u');
	});

	const refused: Array<[string, object]> = [
		['viduq2-pro', {}], ['wan3.0-video', { startImage: 'u' }], ['viduq2', { resolution: '4k' }],
		['viduq2', { seconds: 6 }], ['doubao-seedance-2-5-260628', { seconds: 16 }],
	];
	for (const [model, options] of refused) {
		test(`refused before spending ${model} ${JSON.stringify(options)}`, () => {
			assert.throws(() => SRClient.videoPayload(model, 'p', options), ValidationError);
		});
	}

	test('unlisted model passes', () => {
		assert.equal(SRClient.videoPayload('new-video', 'p', { resolution: '720p', seconds: 9 }).size, '720p');
	});

	test('success and download', async () => {
		const c = client();
		const task = await c.submitVideo('viduq3-turbo', 'p', { resolution: '540p', seconds: 5 });
		const state = await c.waitVideo(task);
		assert.ok(state.done);
		assert.equal((await seen(`/v1/video/generations/${task}`)).length, 2);
		assert.deepEqual((await c.downloadVideo(task)).data, MP4);
		assert.equal((await seen('/v1/videos/'))[0].auth, `Bearer ${KEY}`);
		assert.equal((await seen('/upstream/')).length, 0);
	});

	test('status never exposes the upstream link', async () => {
		const c = client();
		await c.videoStatus('task_ok_2');
		const state = await c.videoStatus('task_ok_2');
		assert.ok(state.done);
		assert.ok(!JSON.stringify(state).includes('upstream'));
	});
});

describe('video downloads that leave the gateway', () => {
	const setContent = (path: string) => fetch(`${BASE}/__content/${path}`);

	test('falls back to the upstream link without the key', async () => {
		await setContent('500');
		const c = client();
		await c.waitVideo('task_ok_3');
		assert.deepEqual((await c.downloadVideo('task_ok_3')).data, MP4);
		assert.equal((await seen('/upstream/video'))[0].auth, null);
	});

	test('gateway redirect drops the key', async () => {
		await setContent('302');
		const c = client();
		await c.waitVideo('task_ok_4');
		assert.deepEqual((await c.downloadVideo('task_ok_4')).data, MP4);
		assert.equal((await seen('/upstream/video'))[0].auth, null);
	});

	test('too large', async () => {
		await setContent('200/huge');
		const c = client();
		await c.waitVideo('task_ok_5');
		await rejects(c.downloadVideo('task_ok_5', 1024), FileTooLarge);
	});

	test('no download without any source', async () => {
		await setContent('404');
		await rejects(client().downloadVideo('t'), SRError);
	});

	test('failure is clean', async () => {
		const err = await rejects(client().waitVideo('task_bad_1'), VideoFailed, /refunded/);
		assertClean(err.message);
	});

	test('wait runs out', async () => {
		const err = (await rejects(client({ videoWaitSeconds: 0 }).waitVideo('task_slow_1'), VideoStillRunning)) as VideoStillRunning;
		assert.equal(err.taskId, 'task_slow_1');
	});

	test('price error', async () => {
		await rejects(client().submitVideo('err-price', 'p'), SRError, /resolution, length or input/);
	});

	test('bad task id sends nothing', async () => {
		await rejects(client().videoStatus('../../etc/passwd'), ValidationError);
		await rejects(client().downloadVideo('../x'), ValidationError);
		assert.equal((await seen()).length, 0);
	});

	test('download hint', () => {
		const hint = videoDownloadHint('task_ok_5', 'https://api.steadyrouter.com');
		assert.ok(hint.includes('task_ok_5/content') && hint.includes('Authorization') && hint.includes('limited time'));
		assert.ok(!hint.includes('upstream'));
	});
});

describe('model lists', () => {
	test('live', async () => {
		const rows = await pricingModels(fetchTransport(), `${BASE}/api/pricing`);
		assert.ok(rows.every((r) => !('group_prices' in r)));
		assert.deepEqual(await listModels('image', { fetch: async () => rows }), ['brand-new-image', 'gpt-image-2']);
		assert.deepEqual(await listModels('image', { family: 'gpt_image', fetch: async () => rows }), ['gpt-image-2']);
	});

	test('falls back to shipped', async () => {
		const boom = async () => {
			throw new Error('down');
		};
		assert.ok((await listModels('video', { family: 'seedance', fetch: boom })).includes('doubao-seedance-2-5-260628'));
		assert.ok(!(await listModels('image', { fetch: boom, exclude: ['mj_imagine'] })).includes('mj_imagine'));
		assert.ok((await listModels('language', { fetch: boom })).length > 100);
	});
});
