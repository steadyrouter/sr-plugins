import type {
	IAuthenticateGeneric,
	ICredentialTestRequest,
	ICredentialType,
	Icon,
	INodeProperties,
} from 'n8n-workflow';

export class SteadyRouterApi implements ICredentialType {
	name = 'steadyRouterApi';

	displayName = 'SteadyRouter API';

	icon: Icon = { light: 'file:../icons/steadyrouter.svg', dark: 'file:../icons/steadyrouter.dark.svg' };

	documentationUrl = '{{get_key_url}}';

	properties: INodeProperties[] = [
		{
			displayName: 'API Key',
			name: 'apiKey',
			type: 'string',
			typeOptions: { password: true },
			required: true,
			default: '',
			description: 'Create a key in the SteadyRouter console under API Keys',
		},
	];

	authenticate: IAuthenticateGeneric = {
		type: 'generic',
		properties: {
			headers: {
				Authorization: '=Bearer {{$credentials.apiKey}}',
			},
		},
	};

	// Listing models costs nothing.
	test: ICredentialTestRequest = {
		request: {
			baseURL: '{{api_base}}',
			url: '/v1/models',
			method: 'GET',
		},
	};
}
