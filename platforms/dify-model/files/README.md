# SteadyRouter

One API key for hundreds of models, with automatic failover between upstream sources.

With smart routing on (the default for new keys), a request that fails in one upstream source is retried in another within the same call, except on 504/524 timeouts.

This plugin adds SteadyRouter as a model provider in Dify: language models (OpenAI, Anthropic, Google, DeepSeek, Qwen, Doubao, GLM, Kimi, Grok and others), text embedding, rerank and speech-to-text.

## Setup

1. [Create a SteadyRouter account]({{sign_up_url}}) and open **API Keys** → **Create API Key** in the console.
2. In Dify, open **Settings** → **Model Provider**, find **SteadyRouter** and paste the key.
3. Pick a SteadyRouter model in your app's model selector.

The key is checked with a free request to the model list, so saving it costs nothing.

## Usage

- Models and current prices are on [Model Square]({{models_url}}).
- A model that is new on SteadyRouter and not in this plugin's list yet can be added under **Add Model**, with its exact name from Model Square.
- Max Tokens matters for small balances: before each request, the gateway reserves balance based on the input plus the maximum output the request asks for.
- Claude and Gemini models are called in OpenAI format here. To use prompt caching or thinking in their native formats, use the [API directly]({{docs_url}}).

## Requirements

- Needs a SteadyRouter API key and outbound HTTPS access to `api.steadyrouter.com`. No other service is contacted.

## Links

- Source code: {{repo_url}}
- Docs: {{docs_url}}
- Privacy: see [PRIVACY.md](PRIVACY.md)
- Contact: {{contact}}
