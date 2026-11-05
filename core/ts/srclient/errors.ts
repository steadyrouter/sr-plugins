// Errors shown to end users. Nothing here may carry a key or an upstream link. Mirrors core/python/srclient/errors.py.

const URL_RE = /(?:https?|ftp):\/\/[^\s"'<>)\]]+/gi;
const KEY_RE = /\b(?:sk|key|token)-[A-Za-z0-9_-]{6,}/g;
const BEARER_RE = /Bearer\s+\S+/gi;
const LIMIT = 300;

/** Remove keys and links from text that came from the gateway or an upstream. */
export function scrub(text: unknown, secret?: string): string {
	let out = String(text ?? '').replace(URL_RE, '[link removed]'); // links first: a key inside a link goes with it
	if (secret) out = out.split(secret).join('[key removed]');
	out = out.replace(BEARER_RE, 'Bearer [key removed]').replace(KEY_RE, '[key removed]');
	return out.split(/\s+/).filter(Boolean).join(' ').slice(0, LIMIT);
}

/** A failure the end user can act on. `message` is always safe to display. */
export class SRError extends Error {
	readonly status?: number;
	readonly code?: string;

	constructor(message: string, options: { status?: number; code?: string } = {}) {
		super(message);
		this.name = 'SRError';
		this.status = options.status;
		this.code = options.code;
	}
}

/** Rejected before any request was sent, so nothing was charged. */
export class ValidationError extends SRError {
	constructor(message: string) {
		super(message);
		this.name = 'ValidationError';
	}
}

/** The task ended in FAILURE. The gateway refunds it. */
export class VideoFailed extends SRError {
	constructor(message: string) {
		super(message);
		this.name = 'VideoFailed';
	}
}

export class VideoStillRunning extends SRError {
	readonly taskId: string;

	constructor(message: string, taskId: string) {
		super(message);
		this.name = 'VideoStillRunning';
		this.taskId = taskId;
	}
}

export class FileTooLarge extends SRError {
	readonly limit: number;

	constructor(message: string, limit: number) {
		super(message);
		this.name = 'FileTooLarge';
		this.limit = limit;
	}
}

const BY_CODE: Record<string, string> = {
	task_price_unsupported: 'This model does not take that resolution, length or input.',
	insufficient_user_quota: 'Your SteadyRouter balance cannot cover this request. Add funds and try again.',
	model_not_found: 'The model name is wrong, or the groups your API key uses do not offer this model.',
};

const BY_STATUS: Record<number, string> = {
	400: 'The request was rejected.',
	401: 'The API key is wrong, disabled, expired or out of its spending cap.',
	403: 'Your SteadyRouter balance cannot cover this request, or this key may not use this model.',
	404: 'The endpoint or model was not found.',
	413: 'The request is too large.',
	429: 'The service is busy. Try again in a little while.',
	503: 'The model name is wrong, or the groups your API key uses do not offer this model.',
};

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Turn an HTTP error reply into a user-facing error. */
export function fromResponse(status: number, body: unknown, secret?: string): SRError {
	let code: unknown;
	let detail: unknown;
	if (isRecord(body)) {
		const err = body.error;
		if (isRecord(err)) {
			code = err.code || err.type;
			detail = err.message;
		} else if (typeof err === 'string') {
			detail = err;
		}
		code = code || body.code;
		detail = detail || body.message;
	}
	const codeText = code ? String(code) : undefined;
	const byCode = codeText ? BY_CODE[codeText] : undefined;
	const known = byCode ?? BY_STATUS[status];
	if (known && (byCode || status !== 400)) return new SRError(known, { status, code: codeText });
	const clean = scrub(detail, secret);
	const base = known ?? `The request failed with HTTP ${status}.`;
	return new SRError(`${base} ${clean}`.trim(), { status, code: codeText });
}
