### What this PR does

Before this PR: SteadyRouter users add a custom provider by hand, and a second one for Anthropic format.

After this PR: SteadyRouter is a built-in provider. SteadyRouter is an AI model API gateway: {{site_url}}. All endpoints are configured at once and the model list is fetched.

Fixes #

### Why we need it and why it was done in this way

The following tradeoffs were made: no OAuth, users paste an API key, so no OAuth service or UI change is needed. The model list comes from `GET /v1/models`, which is OpenAI-shaped, so there is no custom list adapter.

The following alternatives were considered: the `openaiCompatible` helper, which only sets chat and Anthropic endpoints. `defineProvider` is used so embeddings, image generation, responses and Gemini native are configured too.

### Agent Note / Spec

Written with AI assistance (Claude Code). No human code review yet.

Agent Note: N/A — mechanical addition of one provider entry.
Spec PR: N/A
Acceptance criteria: N/A

### Verification

- `pnpm --filter @cherrystudio/provider-registry test`: 647 passed with this change.
- `pnpm --filter @cherrystudio/provider-registry generate`: the SteadyRouter entry it produces is identical to the one in this PR. The rest of its output is left out: it pulls newer catalog data for other providers, and 8 tests about those providers (OpenRouter, Fireworks, LongCat and others) then fail. None of them involve SteadyRouter.
- Ran the app from this branch (`electron-vite dev`, macOS arm64) against the real gateway: the provider shows after TokenDance with its icon, the key check passes, `/v1/models` lists 277 models sorted into types, chat answers, and the painting page returns images from `gpt-image-2-c` and `flux-2-pro`.
- Painting page: `gpt-image-2-c` is our id for GPT Image 2, so it has an override with `modelId: gpt-image-2`. Gemini image models answer on chat completions on SteadyRouter, not on `/v1/images/generations`, so their overrides remove `image-generation` and they stay off the painting page.

### Breaking changes

None.

### Special notes for your reviewer

Files follow the existing provider and icon pattern. Icon, 15 locale labels, system provider ID and product manifest entry are included.

### Checklist

- [x] Branch: This PR targets `main`
- [x] PR: The PR description is expressive enough and will help future contributors
- [x] Code: Write code that humans can understand and Keep it simple
- [ ] Refactor: not applicable
- [x] Upgrade: Impact of this change on upgrade flows was considered and addressed if required
- [x] Documentation: not required
- [ ] Self-review: I have reviewed my own code before requesting review

### Release note

```release-note
Add SteadyRouter as a built-in provider.
```
