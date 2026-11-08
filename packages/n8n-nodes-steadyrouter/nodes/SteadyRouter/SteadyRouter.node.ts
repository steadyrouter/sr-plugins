import type {
	IDataObject,
	IExecuteFunctions,
	ILoadOptionsFunctions,
	INodeExecutionData,
	INodePropertyOptions,
	INodeType,
	INodeTypeDescription,
	JsonObject,
} from 'n8n-workflow';
import { NodeApiError, NodeConnectionTypes, NodeOperationError } from 'n8n-workflow';

import { CREDENTIALS, makeClient, modelOptions } from '../shared/transport';
import {
	SRError,
	ValidationError,
	VideoStillRunning,
	encodeBase64,
	extensionOf,
	sniff,
	type ChatMessage,
	type GeneratedFile,
	type SRClient,
} from '../shared/srclient';
import { properties } from './description';

interface TextOptions {
	systemMessage?: string;
	temperature?: number;
	maxTokens?: number;
	jsonOutput?: boolean;
}

interface ImageOptions {
	aspectRatio?: string;
	imageSize?: string;
	n?: number;
	quality?: string;
	size?: string;
	binaryPropertyOutput?: string;
}

interface VideoOptions {
	resolution?: string;
	seconds?: number;
	startImageField?: string;
	startImageUrl?: string;
	maxWaitMinutes?: number;
	binaryPropertyOutput?: string;
}

async function binaryFile(ctx: IExecuteFunctions, item: number, field: string): Promise<GeneratedFile> {
	const meta = ctx.helpers.assertBinaryData(item, field);
	const data = new Uint8Array(await ctx.helpers.getBinaryDataBuffer(item, field));
	const mime = sniff(data) ?? meta.mimeType;
	if (!mime.startsWith('image/')) {
		throw new NodeOperationError(ctx.getNode(), `The field "${field}" does not hold an image`, { itemIndex: item });
	}
	return { data, mime };
}

async function fileItem(
	ctx: IExecuteFunctions,
	file: GeneratedFile,
	name: string,
	field: string,
	json: IDataObject,
	item: number,
): Promise<INodeExecutionData> {
	const binary = await ctx.helpers.prepareBinaryData(Buffer.from(file.data), `${name}.${extensionOf(file.mime)}`, file.mime);
	return { json: { ...json, mimeType: file.mime, fileSize: file.data.length }, binary: { [field]: binary }, pairedItem: { item } };
}

async function runText(ctx: IExecuteFunctions, client: SRClient, i: number): Promise<INodeExecutionData[]> {
	const model = ctx.getNodeParameter('model', i) as string;
	const prompt = ctx.getNodeParameter('prompt', i) as string;
	const simplify = ctx.getNodeParameter('simplify', i, true) as boolean;
	const options = ctx.getNodeParameter('options', i, {}) as TextOptions;
	const messages: ChatMessage[] = [];
	if (options.systemMessage) messages.push({ role: 'system', content: options.systemMessage });
	messages.push({ role: 'user', content: prompt });
	const out = await client.chat(model, messages, {
		temperature: options.temperature,
		maxTokens: options.maxTokens,
		jsonOutput: options.jsonOutput,
	});
	const json: IDataObject = simplify
		? { text: out.text, model: out.model, finishReason: out.finishReason, usage: out.usage as IDataObject }
		: (out.raw as IDataObject);
	return [{ json, pairedItem: { item: i } }];
}

async function runImage(ctx: IExecuteFunctions, client: SRClient, operation: string, i: number): Promise<INodeExecutionData[]> {
	const model = ctx.getNodeParameter('model', i) as string;
	const prompt = ctx.getNodeParameter('prompt', i) as string;
	const options = ctx.getNodeParameter('options', i, {}) as ImageOptions;
	const images: GeneratedFile[] = [];
	if (operation === 'edit') {
		const fields = (ctx.getNodeParameter('binaryPropertyNames', i) as string)
			.split(',')
			.map((f) => f.trim())
			.filter(Boolean);
		if (!fields.length) throw new NodeOperationError(ctx.getNode(), 'Name at least one input image field', { itemIndex: i });
		for (const field of fields) images.push(await binaryFile(ctx, i, field));
	}
	const files = await client.generateImage(model, prompt, {
		size: options.size || undefined,
		quality: options.quality,
		n: options.n ?? 1,
		aspectRatio: options.aspectRatio,
		imageSize: options.imageSize,
		images,
	});
	const field = options.binaryPropertyOutput || 'data';
	const out: INodeExecutionData[] = [];
	for (const [index, file] of files.entries()) {
		out.push(await fileItem(ctx, file, `image-${index + 1}`, field, { model, index }, i));
	}
	return out;
}

async function runVideo(ctx: IExecuteFunctions, operation: string, i: number): Promise<INodeExecutionData[]> {
	if (operation === 'getStatus') {
		const state = await makeClient(ctx).videoStatus((ctx.getNodeParameter('taskId', i) as string).trim());
		return [{ json: { ...state }, pairedItem: { item: i } }];
	}
	if (operation === 'download') {
		const taskId = (ctx.getNodeParameter('taskId', i) as string).trim();
		const options = ctx.getNodeParameter('downloadOptions', i, {}) as VideoOptions;
		const client = makeClient(ctx);
		const state = await client.videoStatus(taskId); // also tells the client the fallback link, kept inside it
		if (!state.done) {
			throw new NodeOperationError(ctx.getNode(), `The video is not ready yet (status: ${state.status || 'unknown'})`, {
				itemIndex: i,
			});
		}
		const file = await client.downloadVideo(taskId);
		return [await fileItem(ctx, file, `video-${taskId}`, options.binaryPropertyOutput || 'data', { taskId, status: state.status }, i)];
	}
	const model = ctx.getNodeParameter('model', i) as string;
	const prompt = ctx.getNodeParameter('prompt', i) as string;
	const wait = ctx.getNodeParameter('waitForCompletion', i, true) as boolean;
	const options = ctx.getNodeParameter('options', i, {}) as VideoOptions;
	let startImage = options.startImageUrl?.trim() || undefined;
	if (options.startImageField) {
		const image = await binaryFile(ctx, i, options.startImageField.trim());
		startImage = `data:${image.mime};base64,${encodeBase64(image.data)}`;
	}
	const client = makeClient(ctx, { videoWaitSeconds: (options.maxWaitMinutes ?? 8) * 60 });
	const taskId = await client.submitVideo(model, prompt, {
		resolution: options.resolution,
		seconds: options.seconds,
		startImage,
	});
	if (!wait) return [{ json: { taskId, model, status: 'SUBMITTED', done: false }, pairedItem: { item: i } }];
	try {
		const state = await client.waitVideo(taskId);
		const file = await client.downloadVideo(taskId);
		return [await fileItem(ctx, file, `video-${taskId}`, options.binaryPropertyOutput || 'data', { taskId, model, status: state.status, done: true }, i)];
	} catch (error) {
		if (error instanceof VideoStillRunning) {
			return [{ json: { taskId, model, status: 'IN_PROGRESS', done: false, message: error.message }, pairedItem: { item: i } }];
		}
		throw new NodeOperationError(ctx.getNode(), (error as Error).message, { itemIndex: i });
	}
}

export class SteadyRouter implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'SteadyRouter',
		name: 'steadyRouter',
		icon: { light: 'file:../../icons/steadyrouter.svg', dark: 'file:../../icons/steadyrouter.dark.svg' },
		group: ['transform'],
		version: 1,
		subtitle: '={{$parameter["operation"] + ": " + $parameter["resource"]}}',
		description: 'Chat, image and video models through one SteadyRouter API key',
		defaults: { name: 'SteadyRouter' },
		// As an AI tool the Text resource answers directly; image and video results reach the agent as metadata only,
		// since tools cannot pass binary files on.
		usableAsTool: true,
		inputs: [NodeConnectionTypes.Main],
		outputs: [NodeConnectionTypes.Main],
		credentials: [{ name: CREDENTIALS, required: true }],
		properties,
	};

	methods = {
		loadOptions: {
			async getTextModels(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
				return await modelOptions(this, 'language');
			},
			async getImageModels(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
				return await modelOptions(this, 'image');
			},
			async getVideoModels(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
				return await modelOptions(this, 'video');
			},
		},
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const out: INodeExecutionData[] = [];
		const client = makeClient(this);
		for (let i = 0; i < items.length; i++) {
			const resource = this.getNodeParameter('resource', i) as string;
			const operation = this.getNodeParameter('operation', i) as string;
			try {
				if (resource === 'text') out.push(...(await runText(this, client, i)));
				else if (resource === 'image') out.push(...(await runImage(this, client, operation, i)));
				else if (resource === 'video') out.push(...(await runVideo(this, operation, i)));
				else throw new NodeOperationError(this.getNode(), `Unknown resource: ${resource}`, { itemIndex: i });
			} catch (error) {
				// Every SRError message is already scrubbed of keys and upstream links (see srclient/errors.ts).
				const message = error instanceof Error ? error.message : String(error);
				if (this.continueOnFail()) {
					out.push({ json: { error: message }, pairedItem: { item: i } });
					continue;
				}
				if (error instanceof NodeOperationError || error instanceof ValidationError || !(error instanceof SRError)) {
					throw new NodeOperationError(this.getNode(), message, { itemIndex: i });
				}
				throw new NodeApiError(this.getNode(), { message } as JsonObject, {
					message,
					httpCode: error.status ? String(error.status) : undefined,
					itemIndex: i,
				});
			}
		}
		return [out];
	}
}
