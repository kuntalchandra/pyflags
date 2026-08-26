from __future__ import annotations

import threading
from typing import Callable, Optional

from pyflags.domain import Flag


class InvalidFlagConfigError(Exception):
    """Raised at config-set time when a flag config can't be accepted.

    Distinct from Pydantic's ValidationError: that fires when a Flag object
    itself is malformed. This fires when a *valid* Flag object is being
    registered in an invalid way (bad env, unexpected overwrite, wrong type).
    """


class ConfigStore:
    """In-memory, environment-isolated flag config store.

    Thread-safe: set()/get() are guarded by a lock, since the live-update
    poll thread (step 8) will read concurrently with writes from set().
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flags: dict[str, dict[str, Flag]] = {}  # env -> flag_name -> Flag
        self._version = 0
        self._listeners: list[Callable[[], None]] = []

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def register_listener(self, callback: Callable[[], None]) -> None:
        """Register a push-notification callback, invoked after every set()."""
        with self._lock:
            self._listeners.append(callback)

    def set(self, flag: Flag, env: str, *, allow_overwrite: bool = True) -> None:
        if not isinstance(env, str) or not env:
            raise InvalidFlagConfigError("env must be a non-empty string")
        if not isinstance(flag, Flag):
            raise InvalidFlagConfigError(
                f"expected a Flag instance, got {type(flag).__name__}"
            )

        with self._lock:
            env_flags = self._flags.setdefault(env, {})
            if not allow_overwrite and flag.name in env_flags:
                raise InvalidFlagConfigError(
                    f"flag '{flag.name}' already exists in env '{env}' "
                    f"(pass allow_overwrite=True to update it)"
                )
            env_flags[flag.name] = flag
            self._version += 1
            listeners = list(self._listeners)

        # Notify outside the lock - listener code shouldn't hold up the store,
        # and a slow/misbehaving listener shouldn't be able to deadlock set().
        for listener in listeners:
            listener()

    def get(self, flag_name: str, env: str) -> Optional[Flag]:
        if not isinstance(env, str) or not env:
            raise InvalidFlagConfigError("env must be a non-empty string")
        with self._lock:
            return self._flags.get(env, {}).get(flag_name)
