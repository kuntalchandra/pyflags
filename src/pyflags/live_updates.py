from __future__ import annotations

import threading
from typing import Optional, Protocol

from pyflags.config_store import ConfigStore
from pyflags.domain import Flag


class FlagSource(Protocol):
    """Anything FlagEvaluator can read flags from - satisfied by both
    ConfigStore directly and LiveFlagCache, so the evaluator doesn't care
    which one it's wired to."""

    def get(self, flag_name: str, env: str) -> Optional[Flag]: ...


class LiveFlagCache:
    """Local cached view of a ConfigStore, kept fresh via push + poll.

    Simulates the role a real SDK plays against a network-backed config
    source: avoid hitting the source on every evaluate() call, and instead
    refresh a local cache through two independent paths -

    - push: the store notifies us synchronously on every set(), near-instant
    - poll: a background thread checks the store's version counter every
      `poll_interval_seconds` as a safety net, in case a push was missed
      (e.g. this cache started watching a key AFTER a push already fired
      for it, or a listener callback itself failed silently)

    Only watches (flag_name, env) pairs that have actually been requested at
    least once - there's no assumption the store can enumerate all its flags.
    """

    def __init__(self, store: ConfigStore, poll_interval_seconds: float = 2.0) -> None:
        self._store = store
        self._poll_interval = poll_interval_seconds
        self._lock = threading.Lock()
        self._watched: dict[tuple[str, str], Optional[Flag]] = {}
        self._last_synced_version = -1
        self._stop_event = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._store.register_listener(self._on_push)
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=self._poll_interval + 1)

    def get(self, flag_name: str, env: str) -> Optional[Flag]:
        key = (flag_name, env)
        with self._lock:
            if key in self._watched:
                return self._watched[key]

        # First access to this key: fetch once, start watching it going forward.
        flag = self._store.get(flag_name, env)
        with self._lock:
            self._watched[key] = flag
            self._last_synced_version = self._store.version
        return flag

    def _refresh_all_watched(self) -> None:
        with self._lock:
            keys = list(self._watched.keys())
        # Fetch outside our lock - store.get() has its own locking, and we
        # don't want to hold ours while calling into another object.
        refreshed = {key: self._store.get(key[0], key[1]) for key in keys}
        with self._lock:
            self._watched.update(refreshed)
            self._last_synced_version = self._store.version

    def _on_push(self) -> None:
        self._refresh_all_watched()

    def _poll_loop(self) -> None:
        # wait() returns True if stop_event was set, False on timeout -
        # this pattern gives an interruptible sleep instead of time.sleep(),
        # so stop() doesn't have to wait out a full poll interval to return.
        while not self._stop_event.wait(self._poll_interval):
            with self._lock:
                stale = self._store.version != self._last_synced_version
            if stale:
                self._refresh_all_watched()
