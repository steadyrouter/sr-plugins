// The few Workers runtime types this Worker uses, so it type-checks without @cloudflare/workers-types.

interface R2HTTPMetadata {
	contentType?: string;
}

interface R2Range {
	offset?: number;
	length?: number;
	suffix?: number;
}

interface R2Object {
	key: string;
	size: number;
	httpMetadata?: R2HTTPMetadata;
	range?: R2Range;
}

interface R2ObjectBody extends R2Object {
	body: ReadableStream<Uint8Array>;
}

interface R2Bucket {
	head(key: string): Promise<R2Object | null>;
	get(key: string, options?: { range?: Headers | R2Range }): Promise<R2ObjectBody | null>;
	put(
		key: string,
		value: ReadableStream | ArrayBuffer | ArrayBufferView | string,
		options?: { httpMetadata?: R2HTTPMetadata; customMetadata?: Record<string, string> },
	): Promise<R2Object | null>;
}

/** A TransformStream that tells R2 how long the body will be, so a stream can be stored without buffering. */
declare class FixedLengthStream extends TransformStream<Uint8Array, Uint8Array> {
	constructor(length: number);
}

interface Uint8ArrayConstructor {
	fromBase64?(text: string, options?: { alphabet?: 'base64' | 'base64url' }): Uint8Array;
}

interface Env {
	FILES: R2Bucket;
	/** Public base of the file links, e.g. https://files.steadyrouter.com (no trailing slash needed). */
	FILES_BASE_URL: string;
	/** Secret (wrangler secret put). Names a task's video file so a repeated check finds the same file. */
	FILE_NAME_SECRET: string;
}
