# n8n-nodes-steadyrouter

This is an n8n community node package. It lets you use [SteadyRouter]({{site_url}}) models in your n8n workflows: chat with language models, generate and edit images, and generate videos, all with one SteadyRouter API key.

[n8n](https://n8n.io/) is a [fair-code licensed](https://docs.n8n.io/sustainable-use-license/) workflow automation platform.

[Installation](#installation) · [Nodes and operations](#nodes-and-operations) · [Credentials](#credentials) · [Compatibility](#compatibility) · [Usage](#usage) · [Resources](#resources)

## Installation

Follow the [installation guide](https://docs.n8n.io/integrations/community-nodes/installation/) in the n8n community nodes documentation and install `n8n-nodes-steadyrouter`.

## Nodes and operations

**SteadyRouter**

| Resource | Operation | What it does |
|---|---|---|
| Text | Message a Model | Send a prompt (and an optional system message) to a language model and get the reply |
| Image | Generate | Create images from a prompt: Nano Banana (Gemini image models), GPT Image, Seedream, Qwen Image and Wan, Flux and more |
| Image | Edit | Change or combine the images in the input binary fields according to a prompt |
| Video | Generate | Submit a video task (Seedance, Wan, Vidu and more) and, by default, wait for the file |
| Video | Get Status | Check a video task by its ID |
| Video | Download | Get the file of a finished video task |

**SteadyRouter Chat Model**: a chat model for the AI Agent node and the other AI nodes.

## Credentials

1. [Create a SteadyRouter account]({{get_key_url}}), add funds, and open **API Keys** → **Create API Key** in the console.
2. In n8n, create a **SteadyRouter API** credential and paste the key. Saving it checks the key with a free request.

## Compatibility

Tested with n8n {{n8n_version}}. The SteadyRouter Chat Model node needs an n8n version with AI node SDK support.

## Usage

- Model lists load live from SteadyRouter, so new models appear without a node update. If the list cannot be loaded, the node falls back to the list it was released with.
- Images and videos come back as binary data in the `data` field (you can rename it under **Options**), and n8n stores them. Links that expire are never passed on to you.
- A video usually takes from one to a few minutes. **Generate** waits up to 8 minutes by default (change it under **Options**). If the video is not ready by then, the node returns the task ID with `done: false`; use **Get Status** and **Download** later, for example after a Wait node.
- Each video model takes its own resolutions, lengths and starting images: see the [video guide]({{video_docs_url}}). Values a model does not take are refused before anything is sent.
- Current prices are on [Model Square]({{models_url}}). Requests that fail are not charged, and a failed video task is refunded.

## Data and privacy

- The node sends your prompts, input images and settings to SteadyRouter (`api.steadyrouter.com`), which forwards them to the upstream provider that serves the model. See the [privacy policy]({{privacy_url}}).
- It reads the public model list from `www.steadyrouter.com` without your key, and downloads finished files from the storage links in the reply over HTTPS, without your key. Addresses on private networks are refused.
- The node keeps no copy of your files, collects no analytics and does not log your key. n8n stores the key in its own encrypted credentials.

## Resources

- [n8n community nodes documentation](https://docs.n8n.io/integrations/#community-nodes)
- [SteadyRouter docs]({{docs_url}})
- Source code: {{repo_url}}
- Contact: {{contact}}

## Version history

See [CHANGELOG.md](CHANGELOG.md).
