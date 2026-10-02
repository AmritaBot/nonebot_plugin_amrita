from collections.abc import Hashable

import aiologic
from amrita_sense.weakcache import WeakValueLRUCache

from .config import config

_database_lock: WeakValueLRUCache[Hashable, aiologic.Lock] = WeakValueLRUCache(
    capacity=config().amrita_lockpool_size, loose_mode=True
)
_session_lock: WeakValueLRUCache[str, aiologic.Lock] = WeakValueLRUCache(
    capacity=config().amrita_lockpool_size, loose_mode=True
)


def database_lock(*args: Hashable) -> aiologic.Lock:
    if (lock := _database_lock.get(args)) is None:
        lock = aiologic.Lock()
        _database_lock.put(args, lock)
    return lock


def lock_by_session(session_id: str) -> aiologic.Lock:
    if (lock := _session_lock.get(session_id)) is None:
        lock = aiologic.Lock()
        _session_lock.put(session_id, lock)
    return lock
