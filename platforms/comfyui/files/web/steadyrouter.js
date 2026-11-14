// Settings > SteadyRouter: the API key, and where to get one. The key is saved in ComfyUI's user settings on the
// server (user/default/comfy.settings.json), never in a workflow.
import { app } from '../../scripts/app.js';

const GET_KEY_URL = '{{get_key_url}}';

function link() {
	const a = document.createElement('a');
	a.href = GET_KEY_URL;
	a.target = '_blank';
	a.rel = 'noopener noreferrer';
	a.textContent = 'Sign up and create a key (new accounts get free trial credit)';
	return a;
}

app.registerExtension({
	name: 'SteadyRouter.Settings',
	settings: [
		{
			id: 'SteadyRouter.ApiKey',
			category: ['SteadyRouter', 'Account', 'API key'],
			name: 'API key',
			tooltip: 'Used by every SteadyRouter node. Saved on this ComfyUI server, not in workflows.',
			type: 'text',
			sortOrder: 100, // higher comes first: the key, then the link
			defaultValue: '',
			attrs: { type: 'password', autocomplete: 'off', spellcheck: false },
		},
		{
			id: 'SteadyRouter.GetKey',
			category: ['SteadyRouter', 'Account', 'Get a key'],
			name: 'No key yet?',
			type: link,
			sortOrder: 50,
			defaultValue: '',
		},
	],
});
