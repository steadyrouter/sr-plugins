# {{plugin_label}}

{{tagline}}

{{brand}} is an independent API gateway. It is not affiliated with or endorsed by {{owner}}. The model name only says which model this plugin calls.

This plugin has one video tool and one tool to check a video task. For every image and video model on {{brand}}, install **{{brand}} Image & Video** instead. For language models, install the **{{brand}}** model provider plugin.

## Setup

1. [Create a {{brand}} account]({{sign_up_url}}), add funds, and open **API Keys** → **Create API Key** in the console.
2. In Dify, open **Tools** → **{{plugin_label}}** → **Authorize** and paste the key.
3. Add the **{{model}}** tool to your workflow or agent. Choose the model in the tool's settings.

## Tools

| Tool | What it does |
|---|---|
| {{model}} | Generates a video and waits for it |
| Check Video Task | Looks up a video task by its ID and returns the video when ready |

## Usage notes

- The model list loads live from {{brand}}, so a new {{model}} model appears without a plugin update.
- Videos come back as files, which Dify stores. Links that expire are never passed on to you.
- A video usually takes from one to a few minutes. The tool waits up to 8 minutes, then gives you a task ID to use with Check Video Task.
- Videos over 50 MB are too large to attach here. You get the task ID and a command to download the video from {{brand}}. That request must carry your API key, and videos are kept for a limited time only, so save yours soon.
- Each model takes its own resolutions and lengths: see the [video guide]({{video_docs_url}}). Current prices are on [Model Square]({{models_url}}). Requests that fail are not charged, and a failed video task is refunded.
- In a workflow, allow the tool node several minutes before it times out.

## Requirements

- Needs a {{brand}} API key and outbound HTTPS access to `www.steadyrouter.com` (model list) and `api.steadyrouter.com`.
- Files are downloaded from the storage links the gateway returns, over HTTPS, without your key. Addresses on private networks are refused.

## Links

- Source code: {{repo_url}}
- Docs: {{docs_url}}
- Privacy: see [PRIVACY.md](PRIVACY.md)
- Contact: {{contact}}
