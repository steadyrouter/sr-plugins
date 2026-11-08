import { supplyModel } from '@n8n/ai-node-sdk';
import type {
	ILoadOptionsFunctions,
	INodePropertyOptions,
	INodeType,
	INodeTypeDescription,
	ISupplyDataFunctions,
} from 'n8n-workflow';
import { NodeConnectionTypes } from 'n8n-workflow';

import { API_BASE } from '../shared/site';
import { CREDENTIALS, modelOptions } from '../shared/transport';

interface ModelOptions {
	temperature?: number;
	maxTokens?: number;
	topP?: number;
}

export class LmChatSteadyRouter implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'SteadyRouter Chat Model',
		name: 'lmChatSteadyRouter',
		icon: { light: 'file:../../icons/steadyrouter.svg', dark: 'file:../../icons/steadyrouter.dark.svg' },
		group: ['transform'],
		version: [1],
		subtitle: '={{$parameter["model"]}}',
		description: 'Use SteadyRouter language models in AI Agent and other AI nodes',
		defaults: { name: 'SteadyRouter Chat Model' },
		codex: {
			categories: ['assistant'],
			subcategories: {
				AI: ['Language Models', 'Root Nodes'],
				'Language Models': ['Chat Models (Recommended)'],
			},
			resources: { primaryDocumentation: [{ url: 'https://www.steadyrouter.com/site/docs.html' }] },
		},
		inputs: [],
		outputs: [NodeConnectionTypes.AiLanguageModel],
		outputNames: ['Model'],
		credentials: [{ name: CREDENTIALS, required: true }],
		properties: [
			{
				displayName: 'Model Name or ID',
				name: 'model',
				type: 'options',
				typeOptions: { loadOptionsMethod: 'getTextModels' },
				required: true,
				default: '',
				description:
					'The list comes live from SteadyRouter, so new models appear on their own. Choose from the list, or specify an ID using an <a href="https://docs.n8n.io/code/expressions/">expression</a>.',
			},
			{
				displayName: 'Options',
				name: 'options',
				placeholder: 'Add Option',
				description: 'Additional options to add',
				type: 'collection',
				default: {},
				options: [
					{
						displayName: 'Maximum Number of Tokens',
						name: 'maxTokens',
						type: 'number',
						typeOptions: { minValue: 1 },
						default: 1024,
						description: 'The most tokens a reply may use. The gateway reserves this amount up front, so keep it modest.',
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
						displayName: 'Top P',
						name: 'topP',
						type: 'number',
						typeOptions: { minValue: 0, maxValue: 1, numberPrecision: 2 },
						default: 1,
						description: 'Sample only from the most likely tokens whose probabilities add up to this value',
					},
				],
			},
		],
	};

	methods = {
		loadOptions: {
			async getTextModels(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
				return await modelOptions(this, 'language');
			},
		},
	};

	async supplyData(this: ISupplyDataFunctions, itemIndex: number) {
		const credentials = await this.getCredentials(CREDENTIALS);
		const model = this.getNodeParameter('model', itemIndex) as string;
		const options = this.getNodeParameter('options', itemIndex, {}) as ModelOptions;
		return supplyModel(this, {
			type: 'openai',
			baseUrl: `${API_BASE}/v1`,
			apiKey: credentials.apiKey as string,
			model,
			temperature: options.temperature,
			maxCompletionTokens: options.maxTokens,
			topP: options.topP,
		});
	}
}
