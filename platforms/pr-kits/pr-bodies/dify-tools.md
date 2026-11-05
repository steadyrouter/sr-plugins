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

Why it is needed: the model provider plugin only covers Dify's model types, which do not include image or video generation. These tools are all in one plugin, with one key, rather than split across plugins.

## Risk level

- [ ] Low risk
- [x] Medium risk
- [ ] High risk

It sends user content to an external service and processes uploaded files, which are in the Medium definition.

## Required checks

- [x] I have read and followed the Marketplace submission requirements.
- [x] I have read and comply with the Plugin Development Guidelines.
- [x] I tested this plugin on Dify Community Edition and Dify Cloud, or documented any limitation below.
- [x] The package contains only files needed at runtime.
- [x] The package does not contain secrets, local credentials, `.env` files, `.git` directories, virtual environments, caches, logs, or IDE files.
- [x] The package does not contain executables or bundled binaries.
- [x] The plugin README includes setup steps, usage instructions, required APIs or credentials, connection requirements, and the source repository link.
- [x] The plugin includes `PRIVACY.md`, and `manifest.yaml` references it.
- [x] All user-facing text is primarily in English.

## Security and privacy notes

- Requests go to the fixed addresses `https://api.steadyrouter.com` and `https://www.steadyrouter.com` (public model list).
- The gateway may answer with a link to a finished file. The plugin downloads it at once and returns the file: HTTPS only, addresses on private networks refused and rechecked on each redirect, size capped at 50 MB, file type checked, and the API key is never sent to that host. The link is never shown to the user.
- A user may give a public link to a starting image. The plugin does not fetch it: the link is passed to the gateway.
- Errors are scrubbed of keys and links. Requests have timeouts. The plugin stores nothing and does not log the key.

## Local validation

- `dify plugin package`: packaged.
- Dify Community Edition 1.19.0 (local docker), this package: installs; a wrong key is refused with a clear message.
- Same Dify, a build pointed at a local test gateway: the right key is accepted; the model dropdowns load; a tool node in a workflow returns an image file for both a base64 reply and a link reply. The link download carries no key, and the key is not in the output. Video tools ran only in unit tests against the test gateway in this round.
- Dify Community Edition 1.18.0 against the real gateway, 2026-11-02: image tools (Flux, Seedream, Gemini) returned files, the video task checker returned the task state.
- The shared client against the real gateway: images on 2026-11-05 (`gpt-image-2-c`, `flux-2-pro`, `muse-image`), one real video with a first frame on 2026-11-02 (`viduq3-turbo`).
- Not tested on Dify Cloud.

## Reviewer notes

Model dropdowns use `dynamic-select`, read from the public model list, so a new model does not need a new plugin version. Video tools wait up to 8 minutes, below the default 600-second plugin execution limit, and hand back a task ID after that.
