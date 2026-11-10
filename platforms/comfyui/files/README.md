# SteadyRouter for ComfyUI

Chat, image and video models in ComfyUI with one SteadyRouter API key. The nodes run on SteadyRouter's servers, so they need no GPU and no model downloads.

- **Text**: hundreds of language models (GPT, Claude, Gemini, DeepSeek, Qwen, Kimi, Grok and more), for example to write or improve a prompt, or to describe an image.
- **Images**: Nano Banana (Gemini image models), GPT Image, Seedream, Qwen Image and Wan, Flux, Grok Imagine.
- **Video**: Seedance, Wan, Vidu.

## Setup

1. Install **SteadyRouter** from the ComfyUI Manager (or the Comfy Registry) and restart ComfyUI.
2. [Create a SteadyRouter account]({{get_key_url}}), add funds, and open **API Keys** → **Create API Key** in the console.
3. In ComfyUI open **Settings** → **SteadyRouter** and paste the key.
4. Add a node from the **SteadyRouter** category, or search for "SteadyRouter".

The key is never a node input, so it does not travel with workflows you share or with images that carry their workflow. The settings field is saved on the ComfyUI server in `user/default/comfy.settings.json`, where anyone who can open this ComfyUI can read it. Do not save it on a ComfyUI that others can reach. ComfyUI started with `--multi-user` cannot use the key.

## Nodes

| Node | What it does | Output |
|---|---|---|
| SteadyRouter Chat | Any language model. Optional system instructions, images to look at, length limit and JSON output | `text` |
| SteadyRouter Image | Any image model. Connect reference images to edit or combine them | `image` |
| Nano Banana, GPT Image, Seedream, Qwen Image & Wan | The same, showing only that family's models and the settings they take | `image` |
| SteadyRouter Video | Any video model, with an optional first frame. Waits for the video | `video`, `task_id` |
| Seedance, Wan Video, Vidu | The same, showing only that family's models | `video`, `task_id` |
| SteadyRouter Video Task | Picks up a video by its task ID | `video` |

Connect `image` to **Save Image** or **Preview Image**, `video` to **Save Video**, and `text` to any text input (for example the prompt of another node) or to **Preview as Text**.

## Usage notes

- **Every run is a paid request.** ComfyUI reuses the last result while all inputs stay the same; the `seed` input is not sent to the model and only decides that. The image and video nodes pick a new seed on every run, the Chat node keeps its seed until you change it. Current prices are on [Model Square]({{models_url}}). Requests that fail are not charged, and a failed video task is refunded.
- The model lists ship with each release of this package. For a model that is newer than your version, type its name in `custom_model` (an advanced input), or update the package.
- A video usually takes one to a few minutes. The video nodes wait up to `wait_minutes` (8 by default). If the video is not ready by then, the node stops with the task ID in its error message; put that ID into **SteadyRouter Video Task** to pick the video up. Running the video node again would make, and charge for, a second video.
- Each model takes its own resolutions, lengths and first-frame rules: see the [video guide]({{video_docs_url}}). Values a model does not take are refused before anything is sent.
- Videos over 200 MB are not loaded; the error gives the task ID and a command to download the video from SteadyRouter with your key. Videos are kept for a limited time only, so save yours soon.
- Images come back in RGB. If a model returns several images of different sizes, the ones that match the first image's size are kept.

## Privacy

The nodes send your prompts, any images you connect, the settings you choose and your API key to SteadyRouter (`api.steadyrouter.com`), which forwards the request to the upstream provider that serves the model; see SteadyRouter's [Privacy Policy]({{privacy_url}}). Finished files are downloaded over HTTPS from the storage links in the reply, without your key, and handed straight to ComfyUI; addresses on private networks are refused. The package stores nothing, collects no analytics and does not log your key.

## Requirements

- ComfyUI with the V3 node API (`comfy_api.latest`); tested with ComfyUI {{comfyui_version}}.
- Outbound HTTPS access to `api.steadyrouter.com` and to the storage hosts the files come from.

## Links

- Source code: {{repo_url}}
- Docs: {{docs_url}}
- Contact: {{contact}}
