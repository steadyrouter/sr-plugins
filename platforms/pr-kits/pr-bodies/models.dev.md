## Add SteadyRouter

SteadyRouter is an OpenAI-compatible AI model API gateway: {{site_url}}. Docs: {{docs_url}}.

This adds the provider and {{MODEL_COUNT}} popular models, each pointing at its lab entry through `base_model`.

- No `[cost]`: prices vary by upstream source and change often. They are public at {{models_url}}. A sync module can come later.
- Reasoning: `reasoning_effort = low` was sent to each model through the gateway and accepted (2026-11-02, Claude 2026-11-05); the other effort values come from the lab's own host entry. `structured_output` and cache are not declared.
- Reasoning controls probed on 2026-11-06, with the wire fields in each file header: DeepSeek V4 and Qwen have a working toggle; MiniMax too. `thinking_budget` on Qwen was accepted but did not cap reasoning, so `budget` is left out, with the numbers in the header. `kimi-k2.6` keeps the lab's toggle, and the header says its effect was not confirmed on that day.
- `tools.freeform`, probed on 2026-11-06 with a forced custom tool and the regex `ZZ[0-9]{3}`: only `gpt-5.4-mini` enforced it. `gpt-5.4` answers 400, and `gpt-6-astra` and `gpt-6.1-sol` ignore custom tools, so those leave it out. These entries list Chat Completions only.
- `gpt-image-2-c` is the gateway's per-image GPT Image 2 model. It was called on `/v1/images/generations` on 2026-11-05 and returned an image; its `base_model` is `openai/gpt-image-2`.
- `max_completion_tokens` was accepted by every listed model.
- Video models are not included.

`bun validate` passes. `bun run v1:check` exits 1 because a new provider adds to v1: every change is SteadyRouter's own provider fields and its {{MODEL_COUNT}} models being added, and nothing is removed or changed for anyone else. The models are not marked `v2_only` because clients that read v1 (`api.json`) would not see the provider; happy to change that if you prefer.

Tried in OpenCode against a local build of this branch, 2026-11-06: `/connect` saved the key, and `opencode run -m steadyrouter/deepseek-v4-flash` answered without an environment variable. Picking a model through `/models` in the TUI was not confirmed.
