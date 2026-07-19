from __future__ import annotations

from typing import TYPE_CHECKING

from amrita_core import MemoryModel
from amrita_core.base.backend import MemoryBackend

from .memory import CachedUserDataRepository

if TYPE_CHECKING:
    from nonebot_plugin_amrita.agent import AgentSession


class AmritaMemoryBackend(MemoryBackend):
    repo = CachedUserDataRepository()

    def __init__(self, bound: AgentSession):
        self.bound = bound

    async def load_memory(self, session_id: str) -> MemoryModel:
        bound = self.bound
        if (memory := bound.memory_val) is None:
            bound.memory_val = await self.repo.get_memory(session_id)
            memory = bound.memory_val
        return memory.memory_json

    async def commit_memory(self, session_id: str, memory: MemoryModel) -> None:
        memory_val = self.bound.memory_val
        if memory_val is None:
            memory_val = await self.repo.get_memory(session_id)
        if memory_val.memory_json is not memory:
            memory_val.memory_json = memory
        await self.repo.update_memory_data(memory_val)
