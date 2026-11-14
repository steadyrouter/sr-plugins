# SteadyRouter Image & Video Generation

Text to image, image editing and video generation in Dify, with one SteadyRouter API key.

- **Images**: Nano Banana (Gemini image models), GPT Image, Seedream, Qwen Image and Wan, Flux, Grok Imagine.
- **Video**: Seedance, Wan, Vidu.

For language models, install the separate **SteadyRouter** model provider plugin.

## Setup

1. [Create a SteadyRouter account]({{sign_up_url}}) (new accounts get free trial credit to try image generation) and open **API Keys** → **Create API Key** in the console.
2. In Dify, open **Tools** → **SteadyRouter Image & Video Generation** → **Authorize** and paste the key.
3. Add a tool to your workflow or agent. Choose the model in the tool's settings.

## Tools

| Tool | What it does |
|---|---|
| Generate Image | Any image model on SteadyRouter |
| Nano Banana, GPT Image, Seedream, Qwen Image & Wan | The same, showing only that family's models and the settings they take |
| Generate Video | Any video model on SteadyRouter |
| Seedance | The same, showing only Seedance models |
| Check Video Task | Looks up a video task by its ID and returns the video when ready |

## Usage notes

- The model lists load live from SteadyRouter, so new models appear without a plugin update.
- Images and videos come back as files, which Dify stores. Links that expire are never passed on to you.
- A video usually takes from one to a few minutes. The video tools wait up to 8 minutes, then give you a task ID to use with Check Video Task.
- Videos over 50 MB are too large to attach here. You get the task ID and a command to download the video from SteadyRouter. That request must carry your API key, and videos are kept for a limited time only, so save yours soon.
- Each model takes its own resolutions and lengths: see the [video guide]({{video_docs_url}}). Current prices are on [Model Square]({{models_url}}). Requests that fail are not charged, and a failed video task is refunded.
- In a workflow, allow the tool node several minutes before it times out.
- Dify's new **Agents (beta)** cannot take files from tools yet: the run shows "Action failed" and unreadable text even though the image was made and charged. Until Dify fixes this, use the tool in a Workflow, a Chatflow or a classic Agent app.

## Requirements

- Needs a SteadyRouter API key and outbound HTTPS access to `www.steadyrouter.com` (model list) and `api.steadyrouter.com`.
- Files are downloaded from the storage links the gateway returns, over HTTPS, without your key. Addresses on private networks are refused.

## Links

- Source code: {{repo_url}}
- Docs: {{docs_url}}
- Privacy: see [PRIVACY.md](PRIVACY.md)
- Contact: {{contact}}
