"""TG-SignPulse Community Plugin Template."""

from __future__ import annotations

from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "1.0.0"
AUTHOR = "Contributor"


@PluginRegistry.register(
    name="my_plugin_id",
    mode="reactive",
    description="简要描述此插件的功能与特性",
    version=VERSION,
    author=AUTHOR,
    params_schema=[
        {
            "name": "example_param",
            "label": "示例参数",
            "type": "string",
            "default": "default_value",
            "required": False,
            "description": "参数功能说明",
        }
    ],
)
async def handle_action(ctx: PluginContext) -> bool:
    """Plugin execution entrypoint."""
    message = ctx.message
    if not message or not getattr(message, "text", None):
        return False

    param = ctx.params.get("example_param", "default_value")
    ctx.log(f"[my_plugin_id] Processing with param: {param}")

    # Your logic here...
    return True
