# Pydantic Models
from collections.abc import Sequence
from datetime import datetime

from aiologic import Lock
from amrita_core import MemoryModel, UniResponseUsage
from amrita_core.dirty import DirtyAwareModel as BaseModel
from amrita_sense.weakcache import WeakValueLRUCache
from nonebot.adapters import Event
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict as PydConf
from pydantic import Field, field_validator
from typing_extensions import final

from .cache import LRUCache
from .config import config
from .database import InsightsModel, UserDataExecutor, UserMetadata


class BaseSchema(BaseModel):
    """
    Base Schema
    """

    dirty_exclude__: tuple = Field(
        ("id", "user_id", "model_config"), exclude=True, init=False
    )
    readonly__: tuple = Field(
        ("id", "user_id", "model_config"), exclude=True, init=False
    )

    id: int = Field(default=..., description="ID")
    user_id: str = Field(default=..., description="统一用户ID")
    model_config = PydConf(from_attributes=True, strict=False)


class UserMetadataSchema(BaseSchema):
    last_active: datetime = Field(
        default_factory=lambda: datetime.now(), description="最后活跃时间"
    )
    total_called_count: int = Field(default=0, description="长期历史调用次数")
    total_input_token: int = Field(default=0, description="总输入token数")
    total_output_token: int = Field(default=0, description="总输出token数")
    tokens_input: int = Field(default=0, description="当日输入token数")
    tokens_output: int = Field(default=0, description="当日输出token数")
    called_count: int = Field(default=0, description="当日调用次数")


class MemorySchema(BaseSchema):
    memory_json: MemoryModel = Field(
        default_factory=MemoryModel, description="记忆数据的JSON格式"
    )
    extra_prompt: str = Field(default="", description="额外提示")

    @field_validator("extra_prompt", mode="before")
    @classmethod
    def _coerce_extra_prompt(cls, v: str | None) -> str:
        return v or ""


class MemorySessionsSchema(PydanticBaseModel):  # 无脏追踪
    id: int = Field(default=..., description="ID")
    user_id: str = Field(default=..., description="统一用户ID")
    model_config = PydConf(from_attributes=True, strict=False)
    created_at: float = Field(default=0.0, description="创建时间戳")
    data: MemoryModel = Field(
        default_factory=MemoryModel, description="会话数据的JSON格式"
    )


@final
class CachedUserDataRepository:
    _instance = None
    _action_lock: WeakValueLRUCache[str, Lock]
    _cached_memory: LRUCache[str, MemorySchema]
    _cached_metadata: LRUCache[str, UserMetadataSchema]

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._cached_memory = LRUCache(config().amrita_memory_cache_size)
            cls._cached_metadata = LRUCache(
                config().amrita_metadata_cache_size
            )  # 最常访问
            cls._action_lock = WeakValueLRUCache(
                capacity=config().amrita_lockpool_size, loose_mode=True
            )  # 动态锁池
            cls._instance = super().__new__(cls)
        return cls._instance

    def make_lock(self, session_id: str) -> Lock:
        if (lock := self._action_lock.get(session_id)) is None:
            lock = Lock()
            self._action_lock.put(session_id, lock)
        return lock

    @staticmethod
    def make_id(obj: Event | str) -> str:
        return (
            obj
            if isinstance(obj, str)
            else f"{obj.get_event_name()}_{obj.get_session_id()}"
        )

    async def get_memory(self, obj: Event | str) -> MemorySchema:
        uni_id = self.make_id(obj)
        if data := self._cached_memory.get(uni_id):
            return data
        async with self.make_lock(uni_id):
            async with UserDataExecutor(uni_id) as exc:
                conf = await exc.get_or_create_memory()
                data = MemorySchema.model_validate(conf)
            self._cached_memory[uni_id] = data
            return data

    async def get_metadata(self, obj: Event | str) -> UserMetadataSchema:
        uni_id = self.make_id(obj)
        if (
            data := self._cached_metadata.get(uni_id)
        ) and data.last_active.date() == datetime.now().date():
            return data
        async with self.make_lock(uni_id):
            async with UserDataExecutor(uni_id) as exc:
                conf: UserMetadata = await exc.get_or_create_metadata()
                data = UserMetadataSchema.model_validate(conf)
            self._cached_metadata[uni_id] = data
            return data

    async def get_sesssions(self, obj: Event | str) -> Sequence[MemorySessionsSchema]:
        """!此方法没有缓存!"""
        uni_id = self.make_id(obj)
        # 因为缓存数据可能更新不及时，并且更新也麻烦，因为它不常访问，sessions归档这里就没有再做缓存了，只是简单校验了离线模型。
        async with self.make_lock(uni_id):
            async with UserDataExecutor(uni_id) as exc:
                sessions = await exc.get_or_load_sessions()
                data = [MemorySessionsSchema.model_validate(s) for s in sessions]
            return data

    async def update_metadata(self, data: UserMetadataSchema) -> None:
        uni_id = data.user_id
        dirty = data.get_dirty_vars()
        async with self.make_lock(uni_id):
            data.last_active = datetime.now()
            async with UserDataExecutor(uni_id, with_for_update=True) as exc:
                meta = await exc.get_or_create_metadata()
                for attr in dirty:
                    setattr(meta, attr, getattr(data, attr))
        data.clean()
        self._cached_metadata[uni_id] = data

    async def update_memory_data(self, data: MemorySchema):
        uni_id = data.user_id
        # 访问 data.memory_json 本身会把 schema 的 memory_json 字段标记为脏，
        # 因此内层数据的变更以内层模型的脏标记为准。
        memory_dirty = bool(data.memory_json.get_dirty_vars())
        # extra_prompt 与 memory_json 同属一行记录，必须一并写回，
        # 否则仅修改自定义提示词（/prompt set）时会被静默丢弃。
        extra_prompt_dirty = "extra_prompt" in data.get_dirty_vars()
        if not (memory_dirty or extra_prompt_dirty):
            return
        async with self.make_lock(uni_id):
            async with UserDataExecutor(uni_id, with_for_update=True) as executor:
                dt = await executor.get_or_create_memory()
                if memory_dirty:
                    dt.memory_json = data.memory_json.model_dump()
                if extra_prompt_dirty:
                    dt.extra_prompt = data.extra_prompt
        data.clean()
        self._cached_memory[uni_id] = data


def add_usage(
    ins: InsightsModel | UserMetadataSchema, usage: UniResponseUsage[int] | None
):
    if isinstance(ins, InsightsModel):
        if usage:
            ins.token_output += usage.completion_tokens
            ins.token_input += usage.prompt_tokens
        ins.usage_count += 1
    else:
        if usage:
            ins.tokens_input += usage.prompt_tokens
            ins.tokens_output += usage.completion_tokens
            ins.total_input_token += usage.prompt_tokens
            ins.total_output_token += usage.completion_tokens
        ins.called_count += 1
        ins.total_called_count += 1
