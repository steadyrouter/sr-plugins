# Plugin Submission

## Plugin information

- **Author**: steadyrouter
- **Plugin name**: wan_steadyrouter
- **Version**: 0.1.0
- **Source repository**: {{repo_url}}
- **Contact**: {{contact}}

## Submission type

- [x] New plugin
- [ ] Version update

## What changed

Adds a tool that generates videos with Wan through SteadyRouter, a third-party API gateway, and a tool that checks a video task. The video tool lists only the Wan models.

SteadyRouter is not affiliated with Alibaba. This is stated in the plugin description, README and PRIVACY.md. The name says who provides it ("by SteadyRouter"), the icon is our own drawing, not the owner's logo, and no Alibaba logo is used. The model name is there only to say which model the plugin calls.

Why it is needed: TongYi AIGC needs an Alibaba Cloud DashScope key, and the Ace Data Cloud Wan plugin needs an Ace Data Cloud key. This one needs only a SteadyRouter key.

Related plugins: the same author is also submitting SteadyRouter Image & Video, which covers every image and video model with the same API key, and plugins named after other single models. This is a separate listing because people look for this one model by name and want tools with only its models. If you would rather have them consolidated, tell us and we will withdraw this submission.

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
- A user may give a public link to a starting image. The plugin does not fetch it: the link is passed to the gateway. An uploaded starting image is sent to the gateway with the request.
- Errors are scrubbed of keys and links. Requests have timeouts. The plugin stores nothing and does not log the key.

## Local validation

- `dify plugin package`: packaged.
- Dify Community Edition 1.19.0 (local docker), this exact package, next to the other SteadyRouter plugins: installs. A wrong key, checked against the real gateway, is refused with one clear sentence, and the key is not in the reply.
- Same Dify against the real gateway, 2026-11-06, an earlier build: `wan3.0-video` at 480p and 5 seconds returned an 854x480 video file in about 3 minutes. Changes to the build since then are limited to its own icon, the key-check error type, and the shared client's handling of Gemini image models, which this plugin does not call.
- Not tested on Dify Cloud.

## Reviewer notes

The model dropdown uses `dynamic-select` with `form: llm` (under `form: form` the workflow panel of Dify 1.19.0 leaves it empty), read from the public model list and filtered to the Wan models, so a new Wan model does not need a new plugin version. The video tool waits up to 8 minutes, below the default 600-second plugin execution limit, and hands back a task ID after that.
