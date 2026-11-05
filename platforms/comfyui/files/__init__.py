"""SteadyRouter for ComfyUI. Loaded by ComfyUI from custom_nodes/; see README.md."""

from comfy_api.latest import ComfyExtension

from .nodes import NODES

WEB_DIRECTORY = "./web"  # the settings entry for the API key


class SteadyRouterExtension(ComfyExtension):
    async def get_node_list(self):
        return list(NODES)


async def comfy_entrypoint() -> ComfyExtension:
    return SteadyRouterExtension()


__all__ = ["WEB_DIRECTORY", "comfy_entrypoint"]
