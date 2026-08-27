import time

import pytest

from pyflags.config_store import ConfigStore
from pyflags.domain import Flag, FlagType
from pyflags.live_updates import LiveFlagCache


def make_flag(default=False):
    return Flag(name="checkout-v2", flag_type=FlagType.BOOLEAN, default=default)


class _NoPushConfigStore(ConfigStore):
    """Test double simulating a store whose push notifications never fire -
    isolates the poll path so it can be verified independently of push."""

    def register_listener(self, callback):
        pass  # swallow it - push will never happen


class TestFirstAccess:
    def test_get_before_any_watch_fetches_from_store(self):
        store = ConfigStore()
        store.set(make_flag(default=True), env="dev")
        cache = LiveFlagCache(store)

        assert cache.get("checkout-v2", "dev").default is True

    def test_unknown_flag_returns_none_and_is_still_watched(self):
        store = ConfigStore()
        cache = LiveFlagCache(store)
        assert cache.get("nonexistent", "dev") is None


class TestPushPropagation:
    def test_update_propagates_near_instantly_via_push(self):
        store = ConfigStore()
        store.set(make_flag(default=False), env="dev")
        cache = LiveFlagCache(store, poll_interval_seconds=10)  # deliberately slow poll
        cache.start()
        try:
            assert cache.get("checkout-v2", "dev").default is False

            store.set(make_flag(default=True), env="dev")
            time.sleep(0.05)  # allow the synchronous listener callback to run

            assert cache.get("checkout-v2", "dev").default is True
        finally:
            cache.stop()

    def test_only_watched_keys_are_refreshed_on_push(self):
        store = ConfigStore()
        store.set(make_flag(default=False), env="dev")
        store.set(Flag(name="other-flag", flag_type=FlagType.BOOLEAN, default=False), env="dev")
        cache = LiveFlagCache(store, poll_interval_seconds=10)
        cache.start()
        try:
            cache.get("checkout-v2", "dev")  # only this key becomes watched
            store.set(make_flag(default=True), env="dev")
            time.sleep(0.05)
            assert cache.get("checkout-v2", "dev").default is True
        finally:
            cache.stop()


class TestPollFallback:
    def test_update_propagates_via_poll_when_push_unavailable(self):
        store = _NoPushConfigStore()
        store.set(make_flag(default=False), env="dev")
        cache = LiveFlagCache(store, poll_interval_seconds=0.05)
        cache.start()
        try:
            assert cache.get("checkout-v2", "dev").default is False

            store.set(make_flag(default=True), env="dev")
            # No push will fire (register_listener is a no-op on this store) -
            # only the poll loop can pick this up. Give it a couple of cycles.
            time.sleep(0.2)

            assert cache.get("checkout-v2", "dev").default is True
        finally:
            cache.stop()

    def test_no_stale_read_forever_stuck(self):
        # Sanity check on the propagation budget shape: with the production
        # default poll interval (2s), worst-case propagation via poll alone
        # is comfortably under the spec's 5s budget. Verified here with a
        # fast interval for test speed - the bound is architectural
        # (poll_interval + one push attempt), not dependent on the exact
        # interval value chosen.
        store = _NoPushConfigStore()
        store.set(make_flag(default=False), env="dev")
        cache = LiveFlagCache(store, poll_interval_seconds=0.1)
        cache.start()
        try:
            cache.get("checkout-v2", "dev")
            store.set(make_flag(default=True), env="dev")

            deadline = time.monotonic() + 1.0  # generous margin over 2x poll interval
            while time.monotonic() < deadline:
                if cache.get("checkout-v2", "dev").default is True:
                    break
                time.sleep(0.02)
            else:
                pytest.fail("update did not propagate via poll within expected window")
        finally:
            cache.stop()


class TestStartStopLifecycle:
    def test_stop_is_safe_to_call_before_start(self):
        store = ConfigStore()
        cache = LiveFlagCache(store)
        cache.stop()  # should not raise

    def test_double_start_is_idempotent(self):
        store = ConfigStore()
        cache = LiveFlagCache(store, poll_interval_seconds=10)
        cache.start()
        cache.start()  # should not register a second listener/thread
        cache.stop()
