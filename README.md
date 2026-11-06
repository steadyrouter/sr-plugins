# SteadyRouter plugins

Source for the SteadyRouter plugins and provider listings. [SteadyRouter](https://www.steadyrouter.com) is an AI model
API gateway: language, image and video models through one API key.

| Folder | What it builds |
|---|---|
| `platforms/dify-model` | Dify model provider plugin (language, embedding, rerank, speech-to-text) |
| `platforms/dify-tools` | Dify tool plugin (image and video), and plugins named after one model (`single.yaml`) |
| `platforms/n8n` | n8n community node package `n8n-nodes-steadyrouter` |
| `platforms/comfyui` | ComfyUI custom nodes |
| `platforms/coze` | Coze plugins (OpenAPI files) and the Cloudflare Worker they call |
| `platforms/pr-kits` | The files and edits for the provider listings in Cherry Studio, LobeHub, lobe-icons and models.dev |
| `core` | The shared Python and TypeScript clients |
| `catalog` | The model list, generated from the public pricing API |

Every plugin talks only to `https://api.steadyrouter.com` with the user's own API key. No plugin stores the key on our
side or logs it. Dify, n8n and ComfyUI hand generated files to the platform; Coze accepts only links, so the Worker keeps
those files for 15 days and then deletes them.

## Build and test

```
pip install dify_plugin requests pyyaml pytest pytest-timeout cairosvg
python catalog/build_catalog.py       # refresh the model list
python tools/build.py all             # write dist/<platform>
python tools/check.py                 # package contents and generated files
python -m pytest tests -q
```

`make catalog`, `make build P=<platform>`, `make test` and `make check` do the same. The tests use a fake gateway and
need no API key. Some of them skip unless their tools are set up:

- `SR_NODE_TOOLCHAIN`: a folder with TypeScript, `@types/node` and the n8n node CLI installed.
- `SR_COMFYUI` and `SR_COMFY_PYTHON`: a ComfyUI checkout and the Python of its virtual environment.
- `tests/e2e/` runs real n8n, ComfyUI and `wrangler dev` against the fake gateway.

## License

Apache-2.0 (`LICENSE`). The n8n and ComfyUI packages are MIT, each with its own licence file.
