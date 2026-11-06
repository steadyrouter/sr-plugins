# Plugin Submission

## Plugin information

- **Author**: steadyrouter
- **Plugin name**: seedream_steadyrouter
- **Version**: 0.1.0
- **Source repository**: {{repo_url}}
- **Contact**: {{contact}}

## Submission type

- [x] New plugin
- [ ] Version update

## What changed

Adds one tool that generates images with Doubao Seedream through SteadyRouter, a third-party API gateway. The tool lists only the Seedream models.

SteadyRouter is not affiliated with ByteDance. This is stated in the plugin description, README and PRIVACY.md. The name says who provides it ("by SteadyRouter"), the icon is our own drawing, not the owner's logo, and no ByteDance logo is used. The model name is there only to say which model the plugin calls.

Why it is needed: Seedream AIGC needs a Volcengine key, and the Ace Data Cloud Seedream plugin needs an Ace Data Cloud key. This one needs only a SteadyRouter key.

Related plugins: the same author is also submitting SteadyRouter Image & Video, which covers every image and video model with the same API key, and plugins named after other single models. This is a separate listing because people look for this one model by name and want one tool with only its models. If you would rather have them consolidated, tell us and we will withdraw this submission.

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
- Uploaded reference images are sent to the gateway with the request.
- Errors are scrubbed of keys and links. Requests have timeouts. The plugin stores nothing and does not log the key.

## Local validation

- `dify plugin package`: packaged.
- Dify Community Edition 1.19.0 (local docker), this exact package, next to the other SteadyRouter plugins: installs. A wrong key, checked against the real gateway, is refused with one clear sentence, and the key is not in the reply.
- Same Dify against the real gateway, 2026-11-06, an earlier build: the dropdown listed the 3 Seedream models, default `doubao-seedream-4-5-251128`. A workflow returned a 2048x2048 image file. Changes to the build since then are limited to its own icon, the key-check error type, and the shared client's handling of Gemini image models, which this plugin does not call.
- Same Dify, a build pointed at a local test gateway: the right key is accepted; a tool node in a workflow returns an image file.
- Not tested on Dify Cloud.

## Reviewer notes

The model dropdown uses `dynamic-select` with `form: llm` (under `form: form` the workflow panel of Dify 1.19.0 leaves it empty), read from the public model list and filtered to the Seedream models, so a new Seedream model does not need a new plugin version.
