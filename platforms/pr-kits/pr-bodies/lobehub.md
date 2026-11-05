### Summary

Contribution source: AI-assisted

Adds SteadyRouter as a model provider. SteadyRouter is an AI model API gateway: {{site_url}}.

- OpenAI-compatible runtime, with the chat model list fetched from `/v1/models`.
- A few image models on `/v1/images/generations` are listed in model-bank, because `/v1/models` carries no model type.
- Gemini image models answer on chat completions with the image as markdown in `message.content`, which the shared chat route does not read, so the provider has a small `createImage`. Other models use the shared code.
- Provider docs in English and Chinese. The icon is in a separate lobe-icons PR.
- Video is not included: the OpenAI-compatible video path posts to `/videos`, and SteadyRouter's video tasks are on `/v1/video/generations`.

#### Test

- [ ] Tested locally
- [x] Added/updated tests
- [ ] No tests needed

- Acceptance: `vitest run src/providers/steadyrouter` in `packages/model-runtime`: 7 passed. `vitest run` in `packages/model-bank`: 151 passed. A real Gemini image reply on chat completions has the markdown shape `createImage` reads (checked against the gateway on 2026-11-02, outside LobeHub). Not done: the provider has not been opened in the app, so model fetch, a chat and an image have not been tried there.

#### 🔗 Related Issue

None. The icon is in a separate lobe-icons PR.

### AI assistance

- Harness: Claude Code 2.1.318
- Model: claude-opus-5-5
- Thinking level: unknown
- Division of work: AI wrote the provider, tests, docs and this description. SteadyRouter asked for the provider and reviewed this description before it was opened. No human code review yet.
- Implementation rationale: see the Summary. Limitations: no video, and model cards only for image models, because `/v1/models` carries no model type.
- Verification: see Test.
