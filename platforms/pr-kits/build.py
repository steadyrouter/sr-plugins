"""Generate what goes into each upstream repo: new files plus exact edits, applied by tools/apply_pr_kit.py."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from common import DIST, ROOT, Context, fill, fresh_dir

HERE = Path(__file__).resolve().parent
LOGO = (ROOT / "brand" / "logo.svg").read_text().strip()
PATH_D = re.search(r' d="([^"]+)"', LOGO).group(1)
COLOR = "#0f766e"
LOBE_CHAT_IMAGE_MODELS = ["gemini-3.1-flash-image", "gemini-3.1-flash-lite-image", "gemini-3-pro-image"]
LOBE_IMAGE_MODELS = {
    # Models on /v1/images/generations with sizes we can state.
    "gpt-image-2-c": "gpt", "gpt-image-1.5": "gpt", "gpt-image-1": "gpt", "flux-2-pro": "plain",
    "flux-kontext-pro": "plain", "doubao-seedream-4-5-251128": "plain", "qwen-image-3.0": "plain",
    "grok-imagine-image": "plain",
}


def write(root: Path, rel: str, text: str) -> None:
    path = root / "files" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n")


def save_edits(root: Path, edits: list[dict], meta: dict) -> None:
    (root / "kit.json").write_text(json.dumps({**meta, "edits": edits}, indent=1, ensure_ascii=False) + "\n")


def before(file: str, anchor: str, text: str) -> dict:
    return {"file": file, "kind": "before", "anchor": anchor, "text": text}


# ---- models.dev ----

def mono_svg() -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">'
            f'<path d="{PATH_D}" stroke="currentColor" stroke-width="10"/></svg>')


def models_dev(ctx: Context, out: Path) -> None:
    root = fresh_dir(out / "models.dev")
    site = ctx.site
    chosen = yaml.safe_load((HERE / "models-dev-list.yaml").read_text())
    sold = {m["name"] for m in ctx.catalog["models"]}
    missing = (set(chosen["chat"]) | set(chosen["images"])) - sold
    if missing:
        raise SystemExit(f"models-dev-list.yaml lists models not on sale: {sorted(missing)}")
    base = f"providers/{site['slug']}"
    write(root, f"{base}/provider.toml",
          f'name = "{site["brand"]}"\nnpm = "@ai-sdk/openai-compatible"\n'
          f'opencodeai = "@opencode/ai/providers/openai-compatible"\nenv = ["STEADYROUTER_API_KEY"]\n'
          f'api = "{site["api_base"]}/v1"\ndoc = "{site["docs_url"]}"\n')
    write(root, f"{base}/logo.svg", mono_svg())
    for name, spec in chosen["chat"].items():
        probe = f"# Live probe through {site['api_base']}/v1/chat/completions, {spec.get('probed', '2026-11-02')}."
        lines = [probe, "schema = 2", f'base_model = "{spec["lab"]}"', "", "[capabilities]"]
        if spec.get("toggle"):
            lines.append("reasoning = { supported = true, toggle = true }")
        else:
            effort = ", ".join(f'"{e}"' for e in spec["effort"])
            lines.append(f"reasoning = {{ supported = true, effort = [{effort}] }}")
        if spec.get("reasoning_field"):
            lines += ["", "[api.chat-completions]", f'compatibility = {{ reasoning_field = "{spec["reasoning_field"]}" }}']
        write(root, f"{base}/models/{name}.toml", "\n".join(lines))
    for name, spec in chosen["images"].items():
        write(root, f"{base}/models/{name}.toml",
              f'# Images: POST /v1/images/generations ({site["docs_url"]}#images)\nschema = 2\nbase_model = "{spec["lab"]}"\n\n'
              '[api.images]\nsdk = { opencodeai = "@opencode/ai/providers/openai-compatible/images" }\n')
    save_edits(root, [], {"repo": "anomalyco/models.dev", "branch": "add-steadyrouter",
                          "commit": "Add SteadyRouter provider", "sparse": [f"/{base}/**"]})


# ---- Cherry Studio ----

def cherry_registry_entry(site: dict) -> str:
    """providers.json is generated; this matches the generator's formatting so the diff is only this entry."""
    api = site["api_base"]
    return f"""    {{
      "availableInEditions": ["global"],
      "defaultChatEndpoint": "openai-chat-completions",
      "description": "{site['brand']} - AI model provider",
      "endpointConfigs": {{
        "anthropic-messages": {{
          "adapterFamily": "anthropic",
          "baseUrl": "{api}"
        }},
        "google-generate-content": {{
          "adapterFamily": "google",
          "baseUrl": "{api}"
        }},
        "openai-chat-completions": {{
          "adapterFamily": "openai-compatible",
          "baseUrl": "{api}",
          "modelsApiUrls": {{
            "default": "{api}/v1/models"
          }}
        }},
        "openai-embeddings": {{
          "adapterFamily": "openai-compatible",
          "baseUrl": "{api}"
        }},
        "openai-image-generation": {{
          "adapterFamily": "openai-compatible",
          "baseUrl": "{api}"
        }},
        "openai-responses": {{
          "adapterFamily": "openai",
          "baseUrl": "{api}"
        }}
      }},
      "id": "steadyrouter",
      "metadata": {{
        "website": {{
          "apiKey": "{site['get_key_url']}",
          "docs": "{site['docs_url']}",
          "models": "{site['models_url']}",
          "official": "{site['site_url']}"
        }}
      }},
      "name": "{site['brand']}"
    }},
"""


def cherry(ctx: Context, out: Path) -> None:
    root = fresh_dir(out / "cherry-studio")
    site = ctx.for_channel("cherry-studio").site
    api = site["api_base"]
    write(root, "packages/provider-registry/src/providers/steadyrouter.ts", f"""import {{ defineProvider }} from './types'

export default defineProvider({{
  id: 'steadyrouter',
  name: '{site["brand"]}',
  availableInEditions: ['global'],
  defaultChatEndpoint: 'openai-chat-completions',
  endpointConfigs: {{
    'anthropic-messages': {{
      adapterFamily: 'anthropic',
      baseUrl: '{api}'
    }},
    'google-generate-content': {{
      adapterFamily: 'google',
      baseUrl: '{api}'
    }},
    'openai-chat-completions': {{
      adapterFamily: 'openai-compatible',
      baseUrl: '{api}',
      modelsApiUrls: {{ default: '{api}/v1/models' }}
    }},
    'openai-embeddings': {{
      adapterFamily: 'openai-compatible',
      baseUrl: '{api}'
    }},
    'openai-image-generation': {{
      adapterFamily: 'openai-compatible',
      baseUrl: '{api}'
    }},
    'openai-responses': {{
      adapterFamily: 'openai',
      baseUrl: '{api}'
    }}
  }},
  metadata: {{
    website: {{
      apiKey: '{site["get_key_url"]}',
      docs: '{site["docs_url"]}',
      models: '{site["models_url"]}',
      official: '{site["site_url"]}'
    }}
  }}
}})""")
    write(root, "packages/ui/icons/providers/light/steadyrouter.svg", LOGO)
    icons = "packages/ui/src/components/icons/providers"
    write(root, f"{icons}/steadyrouter/meta.ts", f"""import {{ type IconMeta }} from '../../types'

export const meta: IconMeta = {{
  id: 'steadyrouter',
  colorPrimary: '{COLOR}',
  colorScheme: 'color',
  artworkKind: 'tile'
}}""")
    write(root, f"{icons}/steadyrouter/light.tsx", f"""import {{ type SVGProps }} from 'react'

import type {{ IconComponent }} from '../../types'
const SteadyrouterLight: IconComponent = (props: SVGProps<SVGSVGElement>) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" fill="none" viewBox="0 0 64 64" {{...props}}>
    <rect width={{64}} height={{64}} fill="{COLOR}" rx={{14}} />
    <path
      stroke="#fff"
      strokeWidth={{10}}
      d="{PATH_D}"
    />
  </svg>
)
export {{ SteadyrouterLight }}
export default SteadyrouterLight""")
    write(root, f"{icons}/steadyrouter/avatar.tsx", """import { Avatar, AvatarFallback } from '@cherrystudio/ui/components/primitives/avatar'
import { cn } from '@cherrystudio/ui/lib/utils'

import { type IconAvatarProps } from '../../types'
import { SteadyrouterLight } from './light'

export function SteadyrouterAvatar({ size = 32, shape = 'circle', className }: Omit<IconAvatarProps, 'icon'>) {
  return (
    <Avatar
      className={cn('overflow-hidden', shape === 'circle' ? 'rounded-full' : 'rounded-[20%]', className)}
      style={{ width: size, height: size }}>
      <AvatarFallback className="text-foreground">
        <SteadyrouterLight style={{ width: size, height: size }} />
      </AvatarFallback>
    </Avatar>
  )
}""")
    write(root, f"{icons}/steadyrouter/index.tsx", f"""import type {{ CompoundIcon, CompoundIconProps }} from '../../types'
import {{ SteadyrouterAvatar }} from './avatar'
import {{ SteadyrouterLight }} from './light'

const Steadyrouter = ({{ variant, className, ...props }}: CompoundIconProps) => {{
  if (variant === 'light') return <SteadyrouterLight {{...props}} className={{className}} />
  return <SteadyrouterLight {{...props}} className={{className}} />
}}

export const SteadyrouterIcon: CompoundIcon = /*#__PURE__*/ Object.assign(Steadyrouter, {{
  Avatar: SteadyrouterAvatar,
  colorPrimary: '{COLOR}'
}})

export default SteadyrouterIcon""")
    index = "packages/provider-registry/src/providers/index.ts"
    edits = [
        before(index, r"import p_stepfun from", "import p_steadyrouter from './steadyrouter'\n"),
        before(index, r"  p_new_api,", "  p_steadyrouter,\n"),
        before(f"{icons}/catalog.ts", r"import \{ TogetherIcon \}", "import { SteadyrouterIcon } from './steadyrouter'\n"),
        before(f"{icons}/catalog.ts", r"  together: TogetherIcon", "  steadyrouter: SteadyrouterIcon,\n"),
        before(f"{icons}/index.ts", r"export \{ TogetherIcon as", "export { SteadyrouterIcon as Steadyrouter } from './steadyrouter'\n"),
        before(f"{icons}/loaders.ts", r"  together: \(\)", "  steadyrouter: () => import('./steadyrouter').then(({ SteadyrouterIcon }) => SteadyrouterIcon),\n"),
        before(f"{icons}/meta-catalog.ts", r"import \{ meta as togetherMeta \}", "import { meta as steadyrouterMeta } from './steadyrouter/meta'\n"),
        before(f"{icons}/meta-catalog.ts", r"  together: togetherMeta", "  steadyrouter: steadyrouterMeta,\n"),
        before("src/shared/utils/systemProviderId.ts", r"  'stepfun',", "  'steadyrouter',\n"),
        before("src/shared/utils/systemProviderId.ts", r"  stepfun: 'stepfun',", "  steadyrouter: 'steadyrouter',\n"),
        before("src/renderer/i18n/label.ts", r"  stepfun: 'provider\.stepfun'", "  steadyrouter: 'provider.steadyrouter',\n"),
        before("resources/builtin-agents/cherry-assistant/product-manifest.json",
               r'      \{\n        "id": "new-api",',
               f'      {{\n        "id": "steadyrouter",\n        "name": "{site["brand"]}"\n      }},\n'),
        before("packages/provider-registry/data/providers.json", r'    \{\n      "availableInEditions": \[[^\]]*\],\n      "description": "New API',
               cherry_registry_entry(site)),
    ]
    edits.append({"file": "src/renderer/i18n/locales/*.json", "kind": "before_glob",
                  "anchor": r'  "provider\.stepfun"', "text": f'  "provider.steadyrouter": "{site["brand"]}",\n'})
    edits.append({"file": "packages/provider-registry/data/providers.json", "kind": "catalog_version"})
    save_edits(root, edits, {"repo": "CherryHQ/cherry-studio", "branch": "feat/steadyrouter-provider",
                             "commit": "feat(provider): add SteadyRouter", "signoff": True,
                             "sparse": [f"/{icons}/steadyrouter/**", "/packages/provider-registry/src/providers/*.ts",
                                        "/packages/provider-registry/data/providers.json",
                                        "/packages/ui/icons/providers/light/steadyrouter.svg"]})


# ---- LobeHub ----

LOBE_CREATE_IMAGE = """import OpenAI from 'openai';

import type { CreateImageOptions } from '../../core/openaiCompatibleFactory';
import { createOpenAICompatibleImage } from '../../core/openaiCompatibleFactory/createImage';
import type { CreateImagePayload, CreateImageResponse } from '../../types/image';

const MARKDOWN_IMAGE = /!\\[[^\\]]*\\]\\(\\s*(data:image\\/[^)\\s]+|https?:\\/\\/[^)\\s]+)\\s*\\)/;

/**
 * Gemini image models answer on chat completions with the image as markdown in `message.content`,
 * which the shared chat route does not read (it reads `message.images`). Everything else uses the shared code.
 */
export async function createSteadyRouterImage(
  payload: CreateImagePayload,
  options: CreateImageOptions,
): Promise<CreateImageResponse> {
  const client = new OpenAI({ apiKey: options.apiKey, baseURL: options.baseURL ?? undefined });

  if (!payload.model.endsWith(':image')) {
    return createOpenAICompatibleImage(client, payload, options.provider);
  }

  const { imageUrls, prompt } = payload.params;
  const content: OpenAI.Chat.ChatCompletionContentPart[] = [
    { text: prompt, type: 'text' },
    ...(imageUrls ?? []).map((url) => ({ image_url: { url }, type: 'image_url' as const })),
  ];
  const response = await client.chat.completions.create({
    messages: [{ content, role: 'user' }],
    model: payload.model.replace(/:image$/, ''),
    stream: false,
  });

  const text = response.choices[0]?.message?.content ?? '';
  const imageUrl = text.match(MARKDOWN_IMAGE)?.[1];
  if (!imageUrl) throw new Error('No image generated in chat completion response');

  return { imageUrl };
}"""
LOBE_CREATE_IMAGE_TEST = """// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createSteadyRouterImage } from './createImage';

const create = vi.fn();
const generate = vi.fn();

vi.mock('openai', () => ({
  default: vi.fn().mockImplementation(function () {
    return { chat: { completions: { create } }, images: { generate } };
  }),
}));

const options = { apiKey: 'test', baseURL: 'https://example.com/v1', provider: 'steadyrouter' } as any;

describe('createSteadyRouterImage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('reads a markdown data URI from a chat reply', async () => {
    create.mockResolvedValue({
      choices: [{ message: { content: 'Here: ![image](data:image/jpeg;base64,AAAA) done' } }],
    });

    const result = await createSteadyRouterImage(
      { model: 'gemini-3.1-flash-image:image', params: { prompt: 'cat' } } as any,
      options,
    );

    expect(result.imageUrl).toBe('data:image/jpeg;base64,AAAA');
    expect(create.mock.calls[0][0].model).toBe('gemini-3.1-flash-image');
  });

  it('throws when a chat reply has no image', async () => {
    create.mockResolvedValue({ choices: [{ message: { content: 'Sorry, I cannot.' } }] });

    await expect(
      createSteadyRouterImage({ model: 'gemini-3-pro-image:image', params: { prompt: 'cat' } } as any, options),
    ).rejects.toThrow('No image generated');
  });

  it('sends other models to the images endpoint', async () => {
    generate.mockResolvedValue({ data: [{ b64_json: 'AAAA' }] });

    const result = await createSteadyRouterImage(
      { model: 'gpt-image-2-c', params: { prompt: 'cat' } } as any,
      options,
    );

    expect(generate).toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
    expect(result.imageUrl).toContain('AAAA');
  });
});"""


def lobe_image_models(ctx: Context) -> str:
    sold = {m["name"]: m for m in ctx.catalog["models"]}
    blocks = []
    for name, kind in LOBE_IMAGE_MODELS.items():
        if name not in sold:
            raise SystemExit(f"LOBE_IMAGE_MODELS lists a model not on sale: {name}")
        description = sold[name]["description"].replace("'", "\\'")
        size = "\n      size: {\n        default: 'auto',\n        enum: ['auto', '1024x1024', '1536x1024', '1024x1536'],\n      }," if kind == "gpt" else ""
        blocks.append(f"""  {{
    description: '{description}',
    displayName: '{name}',
    enabled: false,
    id: '{name}',
    parameters: {{
      prompt: {{
        default: '',
      }},{size}
    }},
    type: 'image',
  }},""")
    for name in LOBE_CHAT_IMAGE_MODELS:
        if name not in sold:
            raise SystemExit(f"LOBE_CHAT_IMAGE_MODELS lists a model not on sale: {name}")
        description = sold[name]["description"].replace("'", "\\'")
        blocks.append(f"""  {{
    description: '{description}',
    displayName: '{name}',
    enabled: false,
    id: '{name}:image',
    parameters: CHAT_MODEL_IMAGE_GENERATION_PARAMS,
    type: 'image',
  }},""")
    return "\n".join(blocks)


def lobehub(ctx: Context, out: Path) -> None:
    root = fresh_dir(out / "lobehub")
    site = ctx.for_channel("lobehub").site
    api = site["api_base"]
    en = ctx.strings["tagline"]["en_US"]
    zh = ctx.strings["tagline"]["zh_Hans"]
    bank = "packages/model-bank"
    write(root, f"{bank}/src/modelProviders/steadyrouter.ts", f"""import type {{ ModelProviderCard }} from '../types';

const SteadyRouter: ModelProviderCard = {{
  apiKeyUrl: '{site["get_key_url"]}',
  chatModels: [],
  checkModel: 'gpt-5.4-mini',
  description:
    '{en}',
  id: 'steadyrouter',
  modelList: {{ showModelFetcher: true }},
  modelsUrl: '{site["models_url"]}',
  name: '{site["brand"]}',
  settings: {{
    disableBrowserRequest: true,
    proxyUrl: {{
      placeholder: '{api}/v1',
    }},
    sdkType: 'openai',
    showModelFetcher: true,
  }},
  url: '{site["site_url"]}',
}};

export default SteadyRouter;""")
    write(root, f"{bank}/src/aiModels/steadyrouter.ts", f"""import {{ CHAT_MODEL_IMAGE_GENERATION_PARAMS }} from '../standard-parameters';
import type {{ AIImageModelCard }} from '../types/aiModel';

// Chat models come from the gateway's /v1/models, which lists what each key can use.
// Image models are listed here because /v1/models carries no model type.
// A `:image` id is served through chat completions: see createImage in the runtime.
const steadyrouterImageModels: AIImageModelCard[] = [
{lobe_image_models(ctx)}
];

export const allModels = [...steadyrouterImageModels];

export default allModels;""")
    runtime = "packages/model-runtime/src"
    write(root, f"{runtime}/providers/steadyrouter/index.ts", f"""import {{ ModelProvider }} from 'model-bank';

import type {{ OpenAICompatibleFactoryOptions }} from '../../core/openaiCompatibleFactory';
import {{ createOpenAICompatibleRuntime }} from '../../core/openaiCompatibleFactory';
import {{ AgentRuntimeErrorType }} from '../../types/error';
import {{ processMultiProviderModelList }} from '../../utils/modelParse';
import {{ createSteadyRouterImage }} from './createImage';

export interface SteadyRouterModelCard {{
  id: string;
}}

export const params = {{
  baseURL: '{api}/v1',
  createImage: createSteadyRouterImage,
  debug: {{
    chatCompletion: () => process.env.DEBUG_STEADYROUTER_CHAT_COMPLETION === '1',
  }},
  errorType: {{
    bizError: AgentRuntimeErrorType.ProviderBizError,
    invalidAPIKey: AgentRuntimeErrorType.InvalidProviderAPIKey,
  }},
  models: async ({{ client }}) => {{
    const modelsPage = (await client.models.list()) as any;
    const modelList: SteadyRouterModelCard[] = modelsPage.data;

    return processMultiProviderModelList(modelList, 'steadyrouter');
  }},
  provider: ModelProvider.SteadyRouter,
}} satisfies OpenAICompatibleFactoryOptions;

export const LobeSteadyRouterAI = createOpenAICompatibleRuntime(params);""")
    write(root, f"{runtime}/providers/steadyrouter/createImage.ts", LOBE_CREATE_IMAGE)
    write(root, f"{runtime}/providers/steadyrouter/createImage.test.ts", LOBE_CREATE_IMAGE_TEST)
    write(root, f"{runtime}/providers/steadyrouter/index.test.ts", f"""// @vitest-environment node
import {{ ModelProvider }} from 'model-bank';
import {{ describe, expect, it }} from 'vitest';

import {{ testProvider }} from '../../providerTestUtils';
import {{ LobeSteadyRouterAI, params }} from './index';

testProvider({{
  Runtime: LobeSteadyRouterAI,
  provider: ModelProvider.SteadyRouter,
  defaultBaseURL: '{api}/v1',
  chatDebugEnv: 'DEBUG_STEADYROUTER_CHAT_COMPLETION',
  chatModel: 'deepseek-v4-flash',
  invalidErrorType: 'InvalidProviderAPIKey',
  bizErrorType: 'ProviderBizError',
  test: {{
    skipAPICall: true,
    skipErrorHandle: true,
  }},
}});

describe('LobeSteadyRouterAI - params', () => {{
  it('should point at the gateway', () => {{
    expect(params.baseURL).toBe('{api}/v1');
    expect(params.provider).toBe(ModelProvider.SteadyRouter);
  }});
}});""")
    write(root, "docs/usage/providers/steadyrouter.mdx", f"""---
title: Using SteadyRouter in LobeHub
description: Connect LobeHub to SteadyRouter with one API key.
tags:
  - LobeHub
  - SteadyRouter
  - Model gateway
---

# Using SteadyRouter in LobeHub

[SteadyRouter]({site["site_url"]}) is an AI model API gateway: {en[0].lower()}{en[1:]} With smart routing on (the default for new keys), a request that fails in one source is retried in another within the same call, except on 504/524 timeouts.

<Steps>
  ### Step 1: Get an API key

  Create an account on [SteadyRouter]({site["get_key_url"]}), then open **API Keys** in the console and create a key.

  ### Step 2: Configure SteadyRouter in LobeHub

  Open **Settings** → **AI Service Provider**, find **SteadyRouter**, paste the key and turn the provider on.

  ### Step 3: Choose a model

  Click **Fetch models** to load the models your key can use, then pick one in the chat's model selector.
</Steps>

Models and current prices are on [Model Square]({site["models_url"]}). See the [API docs]({site["docs_url"]}) for details.
""")
    write(root, "docs/usage/providers/steadyrouter.zh-CN.mdx", f"""---
title: 在 LobeHub 中使用 SteadyRouter
description: 用一个 API Key 把 LobeHub 接到 SteadyRouter。
tags:
  - LobeHub
  - SteadyRouter
  - 模型网关
---

# 在 LobeHub 中使用 SteadyRouter

[SteadyRouter]({site["site_url"]}) 是 AI 模型 API 网关：{zh}智能路由开着时（新 Key 默认开），一个来源失败会在同一次调用里换下一个来源重试，504 / 524 超时除外。

<Steps>
  ### 步骤一：获取 API Key

  在 [SteadyRouter]({site["get_key_url"]}) 注册账号，到控制台的 **API Keys** 创建一个 Key。

  ### 步骤二：在 LobeHub 中配置

  打开 **设置** → **AI 服务商**，找到 **SteadyRouter**，填入 Key 并打开开关。

  ### 步骤三：选择型号

  点击 **获取模型列表**，加载这个 Key 能用的型号，然后在对话的型号选择器里选一个。
</Steps>

型号和当前价格见[模型广场]({site["models_url"]})，详细用法见 [API 文档]({site["docs_url"]})。
""")
    edits = [
        before(f"{bank}/src/const/modelProvider.ts", r"  Stepfun = 'stepfun',", "  SteadyRouter = 'steadyrouter',\n"),
        before(f"{bank}/src/modelProviders/index.ts", r"import StepfunProvider", "import SteadyRouterProvider from './steadyrouter';\n"),
        before(f"{bank}/src/modelProviders/index.ts", r"  StepfunProvider\.chatModels,", "  SteadyRouterProvider.chatModels,\n"),
        before(f"{bank}/src/modelProviders/index.ts", r"  StepfunProvider,\n", "  SteadyRouterProvider,\n"),
        before(f"{bank}/src/modelProviders/index.ts", r"export \{ default as StepfunProviderCard \}",
               "export { default as SteadyRouterProviderCard } from './steadyrouter';\n"),
        before(f"{bank}/src/aiModels/index.ts", r"import \{ default as stepfun \}", "import { default as steadyrouter } from './steadyrouter';\n"),
        before(f"{bank}/src/aiModels/index.ts", r"  stepfun,\n", "  steadyrouter,\n"),
        before(f"{bank}/src/aiModels/index.ts", r"export \{ default as stepfun \}", "export { default as steadyrouter } from './steadyrouter';\n"),
        before(f"{bank}/package.json", r'    "\./stepfun":', '    "./steadyrouter": "./src/aiModels/steadyrouter.ts",\n'),
        before(f"{runtime}/runtimeMap.ts", r"import \{ LobeStepfunAI \}", "import { LobeSteadyRouterAI } from './providers/steadyrouter';\n"),
        before(f"{runtime}/runtimeMap.ts", r"  stepfun: LobeStepfunAI", "  steadyrouter: LobeSteadyRouterAI,\n"),
        before("locales/en-US/providers.json", r'  "stepfun\.description"', f'  "steadyrouter.description": "{en}",\n'),
        before("locales/zh-CN/providers.json", r'  "stepfun\.description"', f'  "steadyrouter.description": "{zh}",\n'),
    ]
    save_edits(root, edits, {"repo": "lobehub/lobehub", "branch": "feat/steadyrouter-provider",
                             "commit": "✨ feat: add SteadyRouter as a model provider",
                             "sparse": [f"/{runtime}/providers/steadyrouter/**", "/docs/usage/providers/steadyrouter*",
                                        f"/{bank}/src/modelProviders/steadyrouter.ts", f"/{bank}/src/aiModels/steadyrouter.ts"]})


# ---- lobe-icons ----

def lobe_icons(ctx: Context, out: Path) -> None:
    root = fresh_dir(out / "lobe-icons")
    site = ctx.site
    write(root, "src/SteadyRouter/style.ts", f"""export const TITLE = '{site["brand"]}';
export const COLOR_PRIMARY = '{COLOR}';

// Avatar constants
export const AVATAR_BACKGROUND = COLOR_PRIMARY;
export const AVATAR_COLOR = '#fff';
export const AVATAR_ICON_MULTIPLE = 0.7;""")
    write(root, "src/SteadyRouter/components/Mono.tsx", f"""'use client';

import {{ memo }} from 'react';

import type {{ IconType }} from '@/types';

import {{ TITLE }} from '../style';

const Icon: IconType = memo(({{ size = '1em', style, ...rest }}) => {{
  return (
    <svg
      fill="none"
      height={{size}}
      style={{{{ flex: 'none', lineHeight: 1, ...style }}}}
      viewBox="0 0 64 64"
      width={{size}}
      xmlns="http://www.w3.org/2000/svg"
      {{...rest}}
    >
      <title>{{TITLE}}</title>
      <path
        d="{PATH_D}"
        stroke="currentColor"
        strokeWidth={{10}}
      />
    </svg>
  );
}});

export default Icon;""")
    write(root, "src/SteadyRouter/components/Avatar.tsx", """'use client';

import { memo } from 'react';

import IconAvatar, { type IconAvatarProps } from '@/features/IconAvatar';

import { AVATAR_BACKGROUND, AVATAR_COLOR, AVATAR_ICON_MULTIPLE, TITLE } from '../style';
import Mono from './Mono';

export type AvatarProps = Omit<IconAvatarProps, 'Icon'>;

const Avatar = memo<AvatarProps>(({ ...rest }) => {
  return (
    <IconAvatar
      Icon={Mono}
      aria-label={TITLE}
      background={AVATAR_BACKGROUND}
      color={AVATAR_COLOR}
      iconMultiple={AVATAR_ICON_MULTIPLE}
      {...rest}
    />
  );
});

export default Avatar;""")
    write(root, "src/SteadyRouter/index.ts", """import Avatar from './components/Avatar';
import Mono from './components/Mono';
import { COLOR_PRIMARY, TITLE } from './style';

export type CompoundedIcon = typeof Mono & {
  Avatar: typeof Avatar;
  colorPrimary: string;
  title: string;
};

const Icons = Mono as CompoundedIcon;
Icons.Avatar = Avatar;
Icons.colorPrimary = COLOR_PRIMARY;
Icons.title = TITLE;

export default Icons;""")
    write(root, "src/SteadyRouter/index.mdx", f"""---
title: SteadyRouter
description: {site["site_url"]}
category: Provider
---

import {{ SteadyRouter }} from '@lobehub/icons';
import {{ Flexbox }} from '@lobehub/ui';

import ColorPreview from '../components/ColorPreview';
import DocsPreview from '../components/DocsPreview';

## Icons

<DocsPreview>
  {{
    <Flexbox gap={{16}} horizontal>
      <SteadyRouter size={{64}} />
    </Flexbox>
  }}
</DocsPreview>

## Avatars

<DocsPreview>
  {{
    <Flexbox gap={{16}} horizontal>
      <SteadyRouter.Avatar size={{64}} />
      <SteadyRouter.Avatar shape={{'square'}} size={{64}} />
    </Flexbox>
  }}
</DocsPreview>

## Colors

<Flexbox gap={{16}} horizontal>
  <ColorPreview color={{SteadyRouter.colorPrimary}} />
</Flexbox>""")
    edits = [
        before("src/icons.ts", r"export \{ default as Stepfun,",
               "export { default as SteadyRouter, type CompoundedIcon as SteadyRouterProps } from './SteadyRouter';\n"),
        before("src/features/providerEnum.ts", r"  Stepfun = 'stepfun',", "  SteadyRouter = 'steadyrouter',\n"),
        before("src/features/providerConfig.tsx", r"import Stepfun from '@/Stepfun';", "import SteadyRouter from '@/SteadyRouter';\n"),
        before("src/features/providerConfig.tsx", r"  \{ Icon: ZenMux,",
               "  { Icon: SteadyRouter, keywords: [ModelProvider.SteadyRouter] },\n"),
        {"file": "src/toc.json", "kind": "json_toc", "before_id": "Stepfun", "entry": {
            "color": COLOR, "desc": site["site_url"], "docsUrl": "steady-router", "fullTitle": site["brand"],
            "group": "provider", "id": "SteadyRouter",
            "param": {"hasAvatar": True, "hasBrand": False, "hasBrandColor": False, "hasColor": False,
                      "hasCombine": False, "hasText": False, "hasTextCn": False, "hasTextColor": False},
            "title": site["brand"]}},
    ]
    save_edits(root, edits, {"repo": "lobehub/lobe-icons", "branch": "feat/steadyrouter-icon",
                             "commit": "✨ feat: add SteadyRouter icon", "sparse": ["/src/SteadyRouter/**"]})


def pr_bodies(ctx: Context, out: Path) -> None:
    for body in sorted((HERE / "pr-bodies").glob("*.md")):
        target = out / body.stem
        target.mkdir(exist_ok=True)
        count = sum(len(v) for v in yaml.safe_load((HERE / "models-dev-list.yaml").read_text()).values())
        (target / "PR.md").write_text(fill(body.read_text().replace("{{MODEL_COUNT}}", str(count)), ctx))


def build(ctx: Context) -> Path:
    out = fresh_dir(DIST / "pr-kits")
    models_dev(ctx, out)
    cherry(ctx, out)
    lobehub(ctx, out)
    lobe_icons(ctx, out)
    pr_bodies(ctx, out)
    return out
