import type {
	IExecuteFunctions,
	IHttpRequestOptions,
	ILoadOptionsFunctions,
	INodePropertyOptions,
} from 'n8n-workflow';
import { sleep } from 'n8n-workflow';

import { API_BASE, PRICING_API, TEST_BUILD } from './site';
import {
	FileTooLarge,
	SRClient,
	TransportError,
	familyOf,
	generated,
	listModels,
	pricingModels,
	type Category,
	type FormFile,
	type HttpReply,
	type HttpRequest,
	type Transport,
} from './srclient';

export const CREDENTIALS = 'steadyRouterApi';
const USER_AGENT = 'n8n-nodes-steadyrouter';

type Context = IExecuteFunctions | ILoadOptionsFunctions;

function multipart(form: NonNullable<HttpRequest['form']>): { body: Buffer; contentType: string } {
	const boundary = `----steadyrouter${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`;
	const parts: Buffer[] = [];
	const quote = (value: string) => value.replace(/["\r\n]/g, '_');
	for (const [name, value] of Object.entries(form.fields)) {
		parts.push(Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="${quote(name)}"\r\n\r\n${value}\r\n`));
	}
	for (const file of form.files as FormFile[]) {
		parts.push(
			Buffer.from(
				`--${boundary}\r\nContent-Disposition: form-data; name="${quote(file.field)}"; filename="${quote(file.name)}"\r\n` +
					`Content-Type: ${file.mime}\r\n\r\n`,
			),
			Buffer.from(file.data),
			Buffer.from('\r\n'),
		);
	}
	parts.push(Buffer.from(`--${boundary}--\r\n`));
	return { body: Buffer.concat(parts), contentType: `multipart/form-data; boundary=${boundary}` };
}

function isTimeout(error: { code?: string; message?: string }): boolean {
	return ['ECONNABORTED', 'ETIMEDOUT'].includes(error.code ?? '') || /timeout/i.test(error.message ?? '');
}

// n8n passes maxResponseBodyBytes to axios as maxContentLength, which fails with "maxContentLength size of N exceeded".
function isTooLarge(error: Error): boolean {
	return /maxContentLength/i.test(`${error.message} ${(error.cause as Error | undefined)?.message ?? ''}`);
}

/**
 * n8n's request helpers behind the client's transport contract. Requests to the gateway carry the credential
 * through httpRequestWithAuthentication; everything else (upstream file links, the public model list) goes
 * through httpRequest without it. Redirects are never followed here: the client checks every hop itself.
 */
export function n8nTransport(ctx: Context): Transport {
	return {
		async request(req: HttpRequest): Promise<HttpReply> {
			const headers: Record<string, string> = { 'User-Agent': USER_AGENT };
			const options: IHttpRequestOptions = {
				method: req.method,
				url: req.url,
				headers,
				timeout: req.timeoutMs,
				disableFollowRedirect: true,
				returnFullResponse: true,
				ignoreHttpStatusErrors: true,
				encoding: 'arraybuffer',
				json: false,
			};
			if (req.maxBytes) options.maxResponseBodyBytes = req.maxBytes;
			if (req.json !== undefined) {
				headers['Content-Type'] = 'application/json';
				options.body = JSON.stringify(req.json);
			} else if (req.form) {
				const { body, contentType } = multipart(req.form);
				headers['Content-Type'] = contentType;
				options.body = body;
			}
			type Reply = { statusCode: number; headers: Record<string, unknown>; body: unknown };
			// The failure is mapped outside the catch block; the node turns it into a NodeApiError (SteadyRouter.node.ts).
			let failure: Error | undefined;
			const reply: Reply | undefined = await (req.auth
				? ctx.helpers.httpRequestWithAuthentication.call(ctx, CREDENTIALS, options)
				: ctx.helpers.httpRequest(options)
			).catch((error: Error) => {
				failure = error;
				return undefined;
			});
			if (!reply) {
				const error = failure ?? new Error('no reply');
				if (req.maxBytes && isTooLarge(error)) throw new FileTooLarge('The file is larger than the size limit.', req.maxBytes);
				throw new TransportError('request failed', isTimeout(error));
			}
			const raw = reply.body;
			const bytes = Buffer.isBuffer(raw)
				? new Uint8Array(raw)
				: raw instanceof ArrayBuffer
					? new Uint8Array(raw)
					: new Uint8Array(Buffer.from(typeof raw === 'string' ? raw : JSON.stringify(raw ?? '')));
			const out: HttpReply = {
				status: reply.statusCode,
				headers: Object.fromEntries(
					Object.entries(reply.headers ?? {}).map(([k, v]) => [k.toLowerCase(), v === undefined ? undefined : String(v)]),
				),
			};
			if (req.binary) out.bytes = bytes;
			else {
				try {
					out.body = JSON.parse(Buffer.from(bytes).toString('utf8'));
				} catch {
					out.body = undefined;
				}
			}
			return out;
		},
		sleep: async (ms: number) => await sleep(ms),
		now: () => Date.now(),
	};
}

export function makeClient(ctx: Context, options: { videoWaitSeconds?: number } = {}): SRClient {
	return new SRClient(n8nTransport(ctx), {
		baseUrl: API_BASE,
		// Test builds talk to a fake gateway on the local machine; release builds only download public https links.
		httpsOnly: !TEST_BUILD,
		checkHost: TEST_BUILD ? () => undefined : undefined,
		videoWaitSeconds: options.videoWaitSeconds,
	});
}

const EXCLUDE: Record<string, readonly string[]> = {
	language: generated.EXCLUDE['chat-tools'] ?? [],
	image: generated.EXCLUDE['image-tools'] ?? [],
	video: generated.EXCLUDE['image-tools'] ?? [],
};

/** Dropdown options: the live public model list (no key sent), the list shipped in the package if that fails. */
export async function modelOptions(ctx: ILoadOptionsFunctions, category: Category): Promise<INodePropertyOptions[]> {
	const transport = n8nTransport(ctx);
	const names = await listModels(category, {
		exclude: EXCLUDE[category],
		fetch: async () => await pricingModels(transport, PRICING_API),
	});
	return names.map((name) => {
		const family = familyOf(name, generated.FAMILIES);
		const label = family ? `${name} (${generated.FAMILIES[family].label})` : name;
		return { name: label, value: name };
	});
}
