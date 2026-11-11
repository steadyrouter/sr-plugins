# Plugin Submission

## Plugin information

- **Author**: steadyrouter
- **Plugin name**: steadyrouter_image_video
- **Version**: 0.1.0
- **Source repository**: {{repo_url}}
- **Contact**: {{contact}}

## Submission type

- [x] New plugin
- [ ] Version update

## What changed

Adds tools that generate images and videos through one SteadyRouter API key: a tool for any image model, one each for Nano Banana, GPT Image, Seedream, and Qwen Image & Wan, a tool for any video model, one for Seedance, and a task checker for long videos.

Why it is needed: the model provider plugin only covers Dify's model types, which do not include image or video generation. This is the consolidated plugin requested in #3698 and #3699: every image and video model on SteadyRouter, with one key, in one listing. The image and video model dropdowns are read live from SteadyRouter, so Qwen Image, Wan, Vidu and new models appear without a new plugin version.

Related plugins, following the review in #3698 and #3699: we agree that once this plugin is published, the already-published single-model plugins Seedance by SteadyRouter, GPT Image by SteadyRouter and Seedream by SteadyRouter are marked deprecated and point users here; this plugin covers everything they do. The single-model submissions for Qwen Image, Wan and Vidu are closed and will not be resubmitted. The SteadyRouter model provider plugin is not part of this consolidation: it provides Dify model types (LLM, embedding, rerank, speech-to-text), not image or video tools. Nano Banana Pro (`api16/nano_banana_pro`) is not one of the single-model series either: it is an older plugin its original author published long ago, and its version update comes from the original author's own account.

## Risk level

- [ ] Low risk
- [x] Medium risk
- [ ] High risk

It sends user content to an external service and processes uploaded files, which are in the Medium definition.

## Required checks

- [x] I have read and followed the [Marketplace submission requirements](https://github.com/langgenius/dify-plugins/blob/main/docs/plugin-submission-requirements.md).
- [x] I have read and comply with the [Plugin Development Guidelines](https://docs.dify.ai/en/develop-plugin/publishing/standards/contributor-covenant-code-of-conduct).
- [x] I tested this plugin on Dify Community Edition and Dify Cloud, or documented any limitation below.
- [x] The package contains only files needed at runtime.
- [x] The package does not contain secrets, local credentials, `.env` files, `.git` directories, virtual environments, caches, logs, or IDE files.
- [x] The package does not contain executables or bundled binaries, or I explained why they are required below.
- [x] The plugin README includes setup steps, usage instructions, required APIs or credentials, connection requirements, and the source repository link.
- [x] The plugin includes `PRIVACY.md` or a hosted privacy policy, and `manifest.yaml` references it.
- [x] All user-facing text is primarily in English, with any localized README files following the [i18n guidance](https://docs.dify.ai/en/develop-plugin/features-and-specs/plugin-types/multilingual-readme).

## Security and privacy notes

- Requests go to the fixed addresses `https://api.steadyrouter.com` and `https://www.steadyrouter.com` (public model list).
- The gateway may answer with a link to a finished file. The plugin downloads it at once and returns the file: HTTPS only, addresses on private networks refused and rechecked on each redirect, size capped at 50 MB, file type checked, and the API key is never sent to that host. The link is never shown to the user.
- A user may give a public link to a starting image. The plugin does not fetch it: the link is passed to the gateway.
- Errors are scrubbed of keys and links. Requests have timeouts. The plugin stores nothing and does not log the key.

## Local validation

- `dify plugin package`: packaged.
- Dify Community Edition 1.19.0 (local docker), this exact package: installs. A wrong key, checked against the real gateway, is refused with one clear sentence, and the key is not in the reply.
- This exact package against the real gateway, 2026-11-06: `gemini-3.1-flash-lite-image` with 2K selected returned 1376x768 and the message below.
- Same Dify against the real gateway, 2026-11-06, the build before the Gemini Flash Lite rule: the model dropdowns listed 33 image models; Nano Banana (`gemini-3.1-flash-image`) at 2K and 16:9 returned a 2752x1536 image file; GPT Image (`gpt-image-2-c`) returned an image file in about 33 seconds.
- Same Dify, a build pointed at a local test gateway: the right key is accepted; the model dropdowns load; a tool node in a workflow returns an image file for both a base64 reply and a link reply. The link download carries no key, and the key is not in the output. Video tools ran only in unit tests against the test gateway in this round.
- Video through this plugin's shared code against the real gateway, 2026-11-06, in the single-model plugins built from it: Seedance, Wan and Vidu each returned a video file.
- Dify Community Edition 1.18.0 against the real gateway, 2026-11-02: image tools (Flux, Seedream, Gemini) returned files, the video task checker returned the task state.
- The shared client against the real gateway: images on 2026-11-05 (`gpt-image-2-c`, `flux-2-pro`, `muse-image`), one real video with a first frame on 2026-11-02 (`viduq3-turbo`).
- Not tested on Dify Cloud.

## Reviewer notes

Model dropdowns use `dynamic-select` with `form: llm` (under `form: form` the workflow panel of Dify 1.19.0 leaves them empty), read from the public model list, so a new model does not need a new plugin version. Video tools wait up to 8 minutes, below the default 600-second plugin execution limit, and hand back a task ID after that.

`gemini-3.1-flash-lite-image` refuses 2K and 4K, and Dify tool parameters cannot depend on each other, so the plugin sends 1K for that model and says so in a text message: "This model only supports 1K, so 1K was used."
