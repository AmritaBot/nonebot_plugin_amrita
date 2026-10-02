import asyncio
import contextlib
import importlib.util
import sys

from nonebot import require

require("nonebot_plugin_localstore")
require("nonebot_plugin_orm")


from nonebot import get_driver, logger
from nonebot import log as nb_log
from nonebot.plugin import PluginMetadata

if importlib.util.find_spec("amrita") is None:
    from amrita_sense import logging  # 此时AmritaBot没有接管Logger

    logging.logger.remove()

    logging.logger_id.value = logging.logger.add(
        sys.stdout,
        level=0,
        diagnose=False,
        filter=nb_log.default_filter,
        format=nb_log.default_format,
    )

from amrita_core import ChatManager, ChatObject, get_config, load_amrita, set_config
from amrita_core.config import (
    AmritaConfig,
    CookieConfig,
)

from . import agent, database, memory
from . import config as conf_module
from .config import Config
from .database import InsightsModel, UserDataExecutor
from .memory import CachedUserDataRepository, MemorySchema

__plugin_meta__ = PluginMetadata(
    name="LibAmritaCore",
    description="适用于NoneBot2的高性能Agent框架（AmritaCore）支持库",
    usage="View `https://core.amritabot.com/zh` for details.",
    type="library",
    homepage="https://github.com/AmritaBot/nonebot_plugin_amrita",
    config=Config,
    supported_adapters=None,
)


def replace_config(config: Config):

    if not isinstance(config, Config):
        raise TypeError("config must be Config")
    conf_module._config = config


@get_driver().on_startup
async def init():
    _config = conf_module._config
    try:
        am_conf = get_config()
    except RuntimeError:
        # 宿主尚未装配 AmritaCore：本插件作为独立库接管初始化
        am_conf = AmritaConfig()
    # 只在显式开启时叠加，不覆盖宿主已配置的 cookie / MCP，也不重置 llm 与 builtin
    if _config.amrita_cookie_enable:
        am_conf.cookie = CookieConfig(enable_cookie=True, cookie=_config.amrita_cookie)
    if _config.amrita_mcp_enable:
        am_conf.function_config.agent_mcp_client_enable = True
        am_conf.function_config.agent_mcp_server_scripts = list(
            _config.amrita_mcp_clients
        )
    set_config(am_conf)
    await load_amrita()


@get_driver().on_shutdown
async def shutdown():
    logger.info("Shutting down AmritaCore...")

    async def kill_all(objs: list[ChatObject]):
        for obj in objs:
            with contextlib.suppress(Exception):
                obj.terminate()

    await asyncio.gather(
        *[kill_all(objs) for objs in ChatManager().running_chat_object.values()],
        return_exceptions=True,
    )


__all__ = [
    "CachedUserDataRepository",
    "ChatManager",
    "ChatObject",
    "InsightsModel",
    "MemorySchema",
    "UserDataExecutor",
    "agent",
    "database",
    "memory",
]
