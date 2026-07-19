import typing

import typing_extensions
from amrita_core import (
    AgentRuntime as AmRuntime,
)
from amrita_core import (
    AgentStrategy,
    AmritaConfig,
    BackendSlots,
    ChatManager,
    ChatObject,
    ModelPreset,
    PresetManager,
    get_config,
)
from amrita_core.builtins.agent import ReActAgentStrategy
from amrita_core.chatmanager import chat_manager
from amrita_core.consts import DEFAULT_TEMPLATE
from amrita_core.types import Content, Message
from jinja2 import Template
from nonebot.adapters import Event
from nonebot.params import Depends

from nonebot_plugin_amrita.backends import AmritaMemoryBackend
from nonebot_plugin_amrita.database import InsightsModel, make_id
from nonebot_plugin_amrita.lock import lock_by_session
from nonebot_plugin_amrita.memory import (
    CachedUserDataRepository,
    MemorySchema,
    add_usage,
)


class AgentSession(AmRuntime):
    chat_man: ChatManager
    chat_objs: list[ChatObject]
    memory_val: MemorySchema | None = None

    def __init__(
        self,
        config: AmritaConfig,
        preset: ModelPreset,
        train: dict[str, str] | Message[str],
        strategy: type[AgentStrategy] = ReActAgentStrategy,
        template: Template | str = DEFAULT_TEMPLATE,
        session_id: str | None = None,
        backend: BackendSlots | None = None,
        chat_man: ChatManager = chat_manager,
    ):
        super().__init__(
            config,
            preset,
            train,
            strategy,
            template,
            session_id=session_id,
            backend=backend,
        )
        self.chat_objs = []
        self.chat_man = chat_man

    async def __aenter__(self) -> typing_extensions.Self:
        return self

    async def __aexit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        uni_id = self.session_id
        if not self.chat_objs:
            return
        async with lock_by_session(uni_id):  # Thread safe
            insight = await InsightsModel.get()
            dm = CachedUserDataRepository()
            metadata = await dm.get_metadata(uni_id)
            for chat_object in self.chat_objs:
                if (
                    chat_object._di_resp.response
                    and chat_object._di_resp.response.usage
                ):
                    add_usage(metadata, chat_object._di_resp.response.usage)
                    add_usage(insight, chat_object._di_resp.response.usage)
            await insight.save()
            self.chat_objs.clear()

    @classmethod
    async def load_from(
        cls,
        id_or_event: Event | str,
        train: Message[str] | dict[str, str],
        config: AmritaConfig | None = None,
        preset: ModelPreset | None = None,
        strategy: type[AgentStrategy] = ReActAgentStrategy,
        template: Template | str = DEFAULT_TEMPLATE,
        backend: BackendSlots | None = None,
    ) -> "AgentSession":
        uni_id = make_id(id_or_event)
        config = config or get_config()
        preset = preset or PresetManager().get_default_preset()
        return cls(
            config,
            preset,
            train,
            session_id=uni_id,
            strategy=strategy,
            template=template,
            backend=backend,
        )

    def get_backend(self) -> AmritaMemoryBackend:
        return AmritaMemoryBackend(self)

    @typing_extensions.override
    def get_chatobject(
        self, user_input: typing.Sequence[Content] | str | None, **kwargs
    ) -> ChatObject:
        kwargs.update({"chat_man": self.chat_man})
        obj = super().get_chatobject(user_input, **kwargs)
        self.chat_objs.append(obj)
        return obj


def SessionDepends(
    train: Message[str] | dict[str, str],
    config: AmritaConfig | None = None,
    preset: ModelPreset | None = None,
    strategy: type[AgentStrategy] = ReActAgentStrategy,
    template: Template | str = DEFAULT_TEMPLATE,
    backend: BackendSlots | None = None,
):
    async def constructor(event: Event) -> AgentSession:
        return await AgentSession.load_from(
            id_or_event=event,
            train=train,
            config=config,
            preset=preset,
            strategy=strategy,
            template=template,
            backend=backend,
        )

    return Depends(constructor)
