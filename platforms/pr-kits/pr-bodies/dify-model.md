# Plugin Submission

## Plugin information

- **Author**: steadyrouter
- **Plugin name**: steadyrouter
- **Version**: 0.1.0
- **Source repository**: {{repo_url}}
- **Contact**: {{contact}}

## Submission type

- [x] New plugin
- [ ] Version update

## What changed

Adds SteadyRouter as a model provider: language models, text embedding, rerank and speech-to-text through one API key.

Why it is needed: today SteadyRouter users go through OpenAI-API-compatible and add each model by hand, with its context size and limits. This plugin ships the model list with those values filled in, and checks the key with a free request to the model list instead of a paid chat request.

## Risk level

- [ ] Low risk
- [x] Medium risk
- [ ] High risk

It sends user content to an external service (`api.steadyrouter.com`), which is the Medium definition.

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

Requests go only to the fixed address `https://api.steadyrouter.com`. Requests have timeouts. The plugin stores nothing and does not log the key.

## Local validation

- `dify plugin package`: packaged.
- Dify Community Edition 1.19.0 (local docker), this package: installs; a wrong key is refused with a clear message.
- Same Dify, a build pointed at a local test gateway: the right key is accepted; 203 language, 5 embedding, 3 rerank and 3 speech-to-text models are listed; an LLM node in a workflow returns text.
- This plugin's classes against the real gateway, 2026-11-05: chat (blocking and streaming), embedding, rerank. Speech-to-text only ran against the test gateway: the real speech models answered 429 (busy) that day.
- Not tested on Dify Cloud.

## Reviewer notes

The model list is generated from the public model list at {{models_url}}.
