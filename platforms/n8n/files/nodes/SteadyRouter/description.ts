import type { INodeProperties } from 'n8n-workflow';

const show = (resource: string, operation: string[]) => ({ show: { resource: [resource], operation } });

const ASPECTS = ['auto', '1:1', '16:9', '9:16', '4:3', '3:4', '3:2', '2:3', '21:9'];
const RESOLUTIONS = ['480p', '540p', '720p', '1080p', '4k'];
const opts = (values: string[]) => values.map((v) => ({ name: v === 'auto' ? 'Auto' : v, value: v }));

const outputField: INodeProperties = {
	displayName: 'Put Output File in Field',
	name: 'binaryPropertyOutput',
	type: 'string',
	default: 'data',
	hint: 'The name of the output field to put the binary file data in',
};

export const resourceProperty: INodeProperties = {
	displayName: 'Resource',
	name: 'resource',
	type: 'options',
	noDataExpression: true,
	options: [
		{ name: 'Image', value: 'image' },
		{ name: 'Text', value: 'text' },
		{ name: 'Video', value: 'video' },
	],
	default: 'text',
};

const textProperties: INodeProperties[] = [
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['text'] } },
		options: [{ name: 'Message a Model', value: 'message', action: 'Message a model', description: 'Send a prompt to a language model' }],
		default: 'message',
	},
	{
		displayName: 'Model Name or ID',
		name: 'model',
		type: 'options',
		typeOptions: { loadOptionsMethod: 'getTextModels' },
		required: true,
		default: '',
		description:
			'The list comes live from SteadyRouter, so new models appear on their own. Choose from the list, or specify an ID using an <a href="https://docs.n8n.io/code/expressions/">expression</a>.',
		displayOptions: show('text', ['message']),
	},
	{
		displayName: 'Prompt',
		name: 'prompt',
		type: 'string',
		typeOptions: { rows: 4 },
		required: true,
		default: '',
		displayOptions: show('text', ['message']),
	},
	{
		displayName: 'Simplify Output',
		name: 'simplify',
		type: 'boolean',
		default: true,
		description: 'Whether to return only the reply text, model, finish reason and token usage instead of the full response',
		displayOptions: show('text', ['message']),
	},
	{
		displayName: 'Options',
		name: 'options',
		type: 'collection',
		placeholder: 'Add Option',
		default: {},
		displayOptions: show('text', ['message']),
		options: [
			{
				displayName: 'JSON Output',
				name: 'jsonOutput',
				type: 'boolean',
				default: false,
				description: 'Whether to ask the model for a JSON object. Not every model supports it, and the prompt should mention JSON.',
			},
			{
				displayName: 'Maximum Number of Tokens',
				name: 'maxTokens',
				type: 'number',
				typeOptions: { minValue: 1 },
				default: 1024,
				description: 'The most tokens the reply may use. The gateway reserves this amount up front, so keep it modest.',
			},
			{
				displayName: 'Sampling Temperature',
				name: 'temperature',
				type: 'number',
				typeOptions: { minValue: 0, maxValue: 2, numberPrecision: 1 },
				default: 0.7,
				description: 'Lower is more focused and repeatable, higher is more varied. Some reasoning models ignore it.',
			},
			{
				displayName: 'System Message',
				name: 'systemMessage',
				type: 'string',
				typeOptions: { rows: 3 },
				default: '',
				description: 'Instructions the model follows for the whole conversation',
			},
		],
	},
];

const imageProperties: INodeProperties[] = [
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['image'] } },
		options: [
			{ name: 'Edit', value: 'edit', action: 'Edit an image', description: 'Change or combine input images according to a prompt' },
			{ name: 'Generate', value: 'generate', action: 'Generate an image', description: 'Create images from a prompt' },
		],
		default: 'generate',
	},
	{
		displayName: 'Model Name or ID',
		name: 'model',
		type: 'options',
		typeOptions: { loadOptionsMethod: 'getImageModels' },
		required: true,
		default: '',
		description:
			'The list comes live from SteadyRouter, so new models appear on their own. Choose from the list, or specify an ID using an <a href="https://docs.n8n.io/code/expressions/">expression</a>.',
		displayOptions: show('image', ['generate', 'edit']),
	},
	{
		displayName: 'Prompt',
		name: 'prompt',
		type: 'string',
		typeOptions: { rows: 4 },
		required: true,
		default: '',
		description: 'Describe the image you want, or the change to make',
		displayOptions: show('image', ['generate', 'edit']),
	},
	{
		displayName: 'Input Image Fields',
		name: 'binaryPropertyNames',
		type: 'string',
		required: true,
		default: 'data',
		description: 'Names of the input binary fields that hold the images, separated by commas',
		displayOptions: show('image', ['edit']),
	},
	{
		displayName: 'Options',
		name: 'options',
		type: 'collection',
		placeholder: 'Add Option',
		default: {},
		displayOptions: show('image', ['generate', 'edit']),
		options: [
			{
				displayName: 'Aspect Ratio',
				name: 'aspectRatio',
				type: 'options',
				options: opts(ASPECTS),
				default: 'auto',
				description:
					'Used by Gemini image models (Nano Banana). GPT Image models take the nearest size (square, 1536x1024 or 1024x1536) when Size is empty. Other models ignore it.',
			},
			{
				displayName: 'Number of Images',
				name: 'n',
				type: 'number',
				typeOptions: { minValue: 1, maxValue: 4 },
				default: 1,
				description: 'Each image is charged. Gemini image models return one image per request.',
			},
			{ ...outputField },
			{
				displayName: 'Quality',
				name: 'quality',
				type: 'options',
				options: opts(['auto', 'low', 'medium', 'high']),
				default: 'auto',
				description: 'Used by GPT Image models. Higher quality costs more.',
			},
			{
				displayName: 'Resolution',
				name: 'imageSize',
				type: 'options',
				options: opts(['auto', '1K', '2K', '4K']),
				default: 'auto',
				description: 'Used by Gemini image models. Higher costs more.',
			},
			{
				displayName: 'Size',
				name: 'size',
				type: 'string',
				default: '',
				placeholder: '1024x1024',
				description: 'Output size. Each model takes its own sizes; leave empty for the default.',
			},
		],
	},
];

const videoProperties: INodeProperties[] = [
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['video'] } },
		options: [
			{ name: 'Download', value: 'download', action: 'Download a video', description: 'Get the file of a finished video task' },
			{
				name: 'Generate',
				value: 'generate',
				action: 'Generate a video',
				description: 'Submit a video task and, by default, wait for the file',
			},
			{ name: 'Get Status', value: 'getStatus', action: 'Get the status of a video task', description: 'Check a video task by its ID' },
		],
		default: 'generate',
	},
	{
		displayName: 'Model Name or ID',
		name: 'model',
		type: 'options',
		typeOptions: { loadOptionsMethod: 'getVideoModels' },
		required: true,
		default: '',
		description:
			'The list comes live from SteadyRouter, so new models appear on their own. Choose from the list, or specify an ID using an <a href="https://docs.n8n.io/code/expressions/">expression</a>.',
		displayOptions: show('video', ['generate']),
	},
	{
		displayName: 'Prompt',
		name: 'prompt',
		type: 'string',
		typeOptions: { rows: 4 },
		required: true,
		default: '',
		description: 'Describe the video you want',
		displayOptions: show('video', ['generate']),
	},
	{
		displayName: 'Task ID',
		name: 'taskId',
		type: 'string',
		required: true,
		default: '',
		description: 'The ID returned when the video was submitted',
		displayOptions: show('video', ['getStatus', 'download']),
	},
	{
		displayName: 'Wait for Completion',
		name: 'waitForCompletion',
		type: 'boolean',
		default: true,
		description:
			'Whether to wait for the video and return the file. If off, the node returns the task ID at once; use Get Status and Download later.',
		displayOptions: show('video', ['generate']),
	},
	{
		displayName: 'Options',
		name: 'options',
		type: 'collection',
		placeholder: 'Add Option',
		default: {},
		displayOptions: show('video', ['generate']),
		options: [
			{
				displayName: 'Length (Seconds)',
				name: 'seconds',
				type: 'number',
				typeOptions: { minValue: 1, maxValue: 16 },
				default: 5,
				description: 'Each model takes its own lengths. Longer costs more.',
			},
			{
				displayName: 'Maximum Wait (Minutes)',
				name: 'maxWaitMinutes',
				type: 'number',
				typeOptions: { minValue: 1, maxValue: 60 },
				default: 8,
				description: 'If the video is not ready by then, the node returns the task ID instead of failing',
			},
			{ ...outputField },
			{
				displayName: 'Resolution',
				name: 'resolution',
				type: 'options',
				options: opts(RESOLUTIONS),
				default: '720p',
				description: 'Each model takes its own resolutions. Higher costs more.',
			},
			{
				displayName: 'Starting Image Field',
				name: 'startImageField',
				type: 'string',
				default: '',
				description: 'Name of an input binary field holding the first frame. Required by some models, refused by others.',
			},
			{
				displayName: 'Starting Image URL',
				name: 'startImageUrl',
				type: 'string',
				default: '',
				description: 'A public link to the first frame, used if no starting image field is set',
			},
		],
	},
	{
		displayName: 'Options',
		name: 'downloadOptions',
		type: 'collection',
		placeholder: 'Add Option',
		default: {},
		displayOptions: show('video', ['download']),
		options: [{ ...outputField }],
	},
];

export const properties: INodeProperties[] = [resourceProperty, ...textProperties, ...imageProperties, ...videoProperties];
