// Runs the compiled n8n node (a --base-url test build in PKG) against the fake gateway in FAKE_BASE, with a
// stand-in for n8n's execute context. Started by tests/test_n8n.py. The real-n8n run is tests/e2e/n8n_e2e.py.
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { beforeEach, describe, test } = require('node:test');

const PKG = process.env.PKG;
const BASE = process.env.FAKE_BASE;
const KEY = process.env.FAKE_KEY;
const { SteadyRouter } = require(path.join(PKG, 'dist/nodes/SteadyRouter/SteadyRouter.node.js'));
const { LmChatSteadyRouter } = require(path.join(PKG, 'dist/nodes/LmChatSteadyRouter/LmChatSteadyRouter.node.js'));
const { SteadyRouterApi } = require(path.join(PKG, 'dist/credentials/SteadyRouterApi.credentials.js'));
const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.alloc(64)]);

// What n8n's helpers do with the options the transport sets: no redirects, full response, status errors kept,
// body as a Buffer, the credential's header added only by httpRequestWithAuthentication.
async function http(options, auth, key) {
	const headers = { ...(options.headers || {}) };
	if (auth) headers.Authorization = `Bearer ${key}`;
	assert.equal(options.disableFollowRedirect, true);
	assert.equal(options.returnFullResponse, true);
	const reply = await fetch(options.url, { method: options.method, headers, body: options.body, redirect: 'manual' });
	const body = Buffer.from(await reply.arrayBuffer());
	if (options.maxResponseBodyBytes && body.length > options.maxResponseBodyBytes) {
		throw Object.assign(new Error('maxContentLength size of 1024 exceeded'), { code: 'ERR_BAD_RESPONSE' });
	}
	return { statusCode: reply.status, headers: Object.fromEntries(reply.headers), body };
}

function context({ params, items = [{ json: {} }], key = KEY, continueOnFail = false }) {
	const calls = [];
	return {
		calls,
		getInputData: () => items,
		getNodeParameter: (name, _i, fallback) => (name in params ? params[name] : fallback),
		getNode: () => ({ id: '1', name: 'SteadyRouter', type: 'n8n-nodes-steadyrouter.steadyRouter', typeVersion: 1, position: [0, 0], parameters: {} }),
		continueOnFail: () => continueOnFail,
		helpers: {
			httpRequest: (o) => (calls.push(['plain', o.url]), http(o, false, key)),
			httpRequestWithAuthentication(credential, o) {
				assert.equal(credential, 'steadyRouterApi');
				calls.push(['auth', o.url]);
				return http(o, true, key);
			},
			prepareBinaryData: async (data, fileName, mimeType) => ({ data: data.toString('base64'), fileName, mimeType }),
			assertBinaryData: (i, field) => {
				const found = items[i].binary && items[i].binary[field];
				if (!found) throw new Error(`no binary field ${field}`);
				return found;
			},
			getBinaryDataBuffer: async (i, field) => Buffer.from(items[i].binary[field].data, 'base64'),
		},
	};
}

async function run(params, extra = {}) {
	const ctx = context({ params, ...extra });
	const [out] = await new SteadyRouter().execute.call(ctx);
	return { out, ctx };
}

async function seen(prefix = '') {
	const all = await (await fetch(`${BASE}/__seen`)).json();
	return all.filter((r) => r.path.startsWith(prefix));
}

async function fails(promise, pattern) {
	try {
		await promise;
	} catch (err) {
		assert.match(err.message, pattern);
		assert.ok(!err.message.includes(KEY) && !/https?:\/\//.test(err.message), err.message);
		assert.match(err.constructor.name, /^Node(Api|Operation)Error$/);
		return err;
	}
	assert.fail('expected an error');
}

beforeEach(async () => {
	await fetch(`${BASE}/__reset`);
});

describe('description', () => {
	test('names and credential', () => {
		const d = new SteadyRouter().description;
		assert.equal(d.name, 'steadyRouter');
		assert.deepEqual(d.credentials, [{ name: 'steadyRouterApi', required: true }]);
		const cred = new SteadyRouterApi();
		assert.equal(cred.test.request.baseURL, BASE);
		assert.equal(cred.test.request.url, '/v1/models');
		assert.match(cred.documentationUrl, /^https:\/\/www\.steadyrouter\.com\/sign-up/);
		assert.equal(cred.authenticate.properties.headers.Authorization, '=Bearer {{$credentials.apiKey}}');
	});
});

describe('text', () => {
	test('message a model, simplified', async () => {
		const { out } = await run({
			resource: 'text', operation: 'message', model: 'some-chat', prompt: 'hi', simplify: true,
			options: { systemMessage: 'be brief', maxTokens: 64, temperature: 0.3 },
		});
		assert.equal(out[0].json.text, 'Hello');
		assert.equal(out[0].json.finishReason, 'stop');
		const body = (await seen('/v1/chat/completions'))[0].body;
		assert.deepEqual(body.messages[0], { role: 'system', content: 'be brief' });
		assert.equal(body.max_completion_tokens, 64);
		assert.equal((await seen('/v1/chat/completions'))[0].auth, `Bearer ${KEY}`);
	});

	test('raw output', async () => {
		const { out } = await run({ resource: 'text', operation: 'message', model: 'some-chat', prompt: 'hi', simplify: false });
		assert.equal(out[0].json.choices[0].message.content, 'Hello');
	});

	test('wrong key is an API error without the key', async () => {
		const ctx = context({ params: { resource: 'text', operation: 'message', model: 'some-chat', prompt: 'hi' }, key: 'sk-wrong-key-000000' });
		const err = await fails(new SteadyRouter().execute.call(ctx), /API key/);
		assert.equal(err.constructor.name, 'NodeApiError');
	});

	test('continue on fail returns the clean error', async () => {
		const { out } = await run({ resource: 'image', operation: 'generate', model: 'err-leak', prompt: 'cat' }, { continueOnFail: true });
		assert.match(out[0].json.error, /418/);
		assert.ok(!out[0].json.error.includes(KEY));
	});
});

describe('image', () => {
	test('generate from b64', async () => {
		const { out } = await run({ resource: 'image', operation: 'generate', model: 'm-b64', prompt: 'cat', options: {} });
		assert.equal(out.length, 1);
		assert.equal(out[0].binary.data.mimeType, 'image/png');
		assert.equal(out[0].binary.data.fileName, 'image-1.png');
		assert.deepEqual(Buffer.from(out[0].binary.data.data, 'base64'), PNG);
	});

	test('generate from a link: downloaded without the key, into the chosen field', async () => {
		const { out, ctx } = await run({ resource: 'image', operation: 'generate', model: 'm-url', prompt: 'cat', options: { binaryPropertyOutput: 'picture' } });
		assert.ok(out[0].binary.picture);
		assert.equal((await seen('/upstream/'))[0].auth, null);
		assert.ok(ctx.calls.some(([kind, url]) => kind === 'plain' && url.includes('/upstream/')));
		assert.ok(!JSON.stringify(out[0].json).includes('upstream'));
	});

	test('gemini through chat with aspect ratio', async () => {
		const { out } = await run({ resource: 'image', operation: 'generate', model: 'gemini-md-data-image', prompt: 'cat', options: { aspectRatio: '16:9', imageSize: '2K' } });
		assert.equal(out[0].binary.data.mimeType, 'image/png');
		const body = (await seen('/v1/chat/completions'))[0].body;
		assert.deepEqual(body.extra_body, { google: { image_config: { aspect_ratio: '16:9', image_size: '2K' } } });
	});

	test('edit sends the input images as multipart', async () => {
		const items = [{ json: {}, binary: { a: { data: PNG.toString('base64'), mimeType: 'image/png' }, b: { data: PNG.toString('base64'), mimeType: 'image/png' } } }];
		const { out } = await run({ resource: 'image', operation: 'edit', model: 'm-b64', prompt: 'merge', binaryPropertyNames: 'a, b', options: {} }, { items });
		assert.equal(out[0].binary.data.mimeType, 'image/png');
		const request = (await seen('/v1/images/edits'))[0];
		assert.match(request.ctype, /^multipart\/form-data; boundary=/);
		assert.match(String(request.body), /bytes/);
	});

	test('edit refuses a field that is not an image', async () => {
		const items = [{ json: {}, binary: { a: { data: Buffer.from('hello').toString('base64'), mimeType: 'text/plain' } } }];
		await fails(run({ resource: 'image', operation: 'edit', model: 'm-b64', prompt: 'x', binaryPropertyNames: 'a', options: {} }, { items }), /does not hold an image/);
		assert.equal((await seen()).length, 0);
	});

	test('oversize download stops', async () => {
		// The fake's file is 4 KB over a 50 MB limit only in Python tests; here the helper reports the n8n-side cap.
		const ctx = context({ params: { resource: 'image', operation: 'generate', model: 'm-url-huge', prompt: 'cat', options: {} } });
		const original = ctx.helpers.httpRequest;
		ctx.helpers.httpRequest = (o) => original({ ...o, maxResponseBodyBytes: 1024 });
		await fails(new SteadyRouter().execute.call(ctx), /size limit/);
	});
});

describe('video', () => {
	test('generate and wait returns the file', async () => {
		const { out } = await run({ resource: 'video', operation: 'generate', model: 'viduq3-turbo', prompt: 'p', waitForCompletion: true, options: { resolution: '540p', seconds: 5 } });
		assert.equal(out[0].json.done, true);
		assert.equal(out[0].binary.data.mimeType, 'video/mp4');
		assert.equal((await seen('/v1/videos/'))[0].auth, `Bearer ${KEY}`);
		assert.equal((await seen('/upstream/')).length, 0);
		assert.deepEqual((await seen('/v1/video/generations'))[0].body, { model: 'viduq3-turbo', prompt: 'p', size: '540p', duration: 5 });
	});

	test('generate without waiting returns the task ID', async () => {
		const { out } = await run({ resource: 'video', operation: 'generate', model: 'viduq3-turbo', prompt: 'p', waitForCompletion: false, options: {} });
		assert.deepEqual(out[0].json, { taskId: 'task_ok_1', model: 'viduq3-turbo', status: 'SUBMITTED', done: false });
	});

	test('starting image from a binary field goes as a data URI', async () => {
		const items = [{ json: {}, binary: { frame: { data: PNG.toString('base64'), mimeType: 'image/png' } } }];
		await run({ resource: 'video', operation: 'generate', model: 'viduq2-pro', prompt: 'p', waitForCompletion: false, options: { startImageField: 'frame' } }, { items });
		const body = (await seen('/v1/video/generations'))[0].body;
		assert.match(body.images[0], /^data:image\/png;base64,/);
	});

	test('values the model refuses are stopped before sending', async () => {
		await fails(run({ resource: 'video', operation: 'generate', model: 'viduq2', prompt: 'p', options: { resolution: '4k' } }), /resolutions/);
		assert.equal((await seen()).length, 0);
	});

	test('get status hides the upstream link', async () => {
		await run({ resource: 'video', operation: 'getStatus', taskId: 'task_ok_7' });
		const { out } = await run({ resource: 'video', operation: 'getStatus', taskId: 'task_ok_7' });
		assert.equal(out[0].json.status, 'SUCCESS');
		assert.ok(!JSON.stringify(out[0].json).includes('upstream'));
	});

	test('download of an unfinished task is refused', async () => {
		await fails(run({ resource: 'video', operation: 'download', taskId: 'task_slow_2', downloadOptions: {} }), /not ready/);
	});

	test('download falls back to the upstream link without the key', async () => {
		await fetch(`${BASE}/__content/500`);
		await run({ resource: 'video', operation: 'getStatus', taskId: 'task_ok_8' });
		const { out } = await run({ resource: 'video', operation: 'download', taskId: 'task_ok_8', downloadOptions: {} });
		assert.equal(out[0].binary.data.mimeType, 'video/mp4');
		assert.equal((await seen('/upstream/video'))[0].auth, null);
	});

	test('a failed task reports a clean reason', async () => {
		const { out } = await run({ resource: 'video', operation: 'getStatus', taskId: 'task_bad_1' });
		assert.equal(out[0].json.failed, true);
		assert.match(out[0].json.failReason, /upstream refused/);
		assert.ok(!out[0].json.failReason.includes(KEY) && !out[0].json.failReason.includes('secret.example'));
	});
});

describe('model lists', () => {
	test('live list, no key sent, families labelled', async () => {
		const ctx = context({ params: {} });
		const options = await new SteadyRouter().methods.loadOptions.getImageModels.call(ctx);
		assert.deepEqual(options.map((o) => o.value), ['brand-new-image', 'gpt-image-2']);
		assert.equal(options[1].name, 'gpt-image-2 (GPT Image)');
		assert.equal((await seen('/api/pricing'))[0].auth, null);
	});

	test('falls back to the shipped list', async () => {
		const ctx = context({ params: {} });
		ctx.helpers.httpRequest = async () => {
			throw new Error('down');
		};
		const video = await new SteadyRouter().methods.loadOptions.getVideoModels.call(ctx);
		assert.ok(video.some((o) => o.value === 'doubao-seedance-2-5-260628'));
		const text = await new LmChatSteadyRouter().methods.loadOptions.getTextModels.call(ctx);
		assert.ok(text.length > 100 && !text.some((o) => o.value === 'o3-pro'));
		const images = await new SteadyRouter().methods.loadOptions.getImageModels.call(ctx);
		assert.ok(!images.some((o) => o.value.startsWith('mj_')));
	});
});
