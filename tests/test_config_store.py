import pytest

from pyflags.config_store import ConfigStore, InvalidFlagConfigError
from pyflags.domain import Flag, FlagType


def make_flag(name="checkout-v2", default=False):
    return Flag(name=name, flag_type=FlagType.BOOLEAN, default=default)


class TestEnvironmentIsolation:
    def test_same_flag_name_different_envs_are_independent(self):
        store = ConfigStore()
        store.set(make_flag(default=True), env="dev")
        store.set(make_flag(default=False), env="prod")

        assert store.get("checkout-v2", env="dev").default is True
        assert store.get("checkout-v2", env="prod").default is False

    def test_get_unknown_flag_returns_none(self):
        store = ConfigStore()
        assert store.get("nonexistent", env="dev") is None

    def test_get_known_flag_wrong_env_returns_none(self):
        store = ConfigStore()
        store.set(make_flag(), env="dev")
        assert store.get("checkout-v2", env="staging") is None


class TestSetValidation:
    def test_empty_env_rejected(self):
        store = ConfigStore()
        with pytest.raises(InvalidFlagConfigError):
            store.set(make_flag(), env="")

    def test_non_flag_object_rejected(self):
        store = ConfigStore()
        with pytest.raises(InvalidFlagConfigError):
            store.set({"name": "not-a-flag"}, env="dev")

    def test_overwrite_allowed_by_default(self):
        store = ConfigStore()
        store.set(make_flag(default=False), env="dev")
        store.set(make_flag(default=True), env="dev")  # no error
        assert store.get("checkout-v2", env="dev").default is True

    def test_overwrite_rejected_when_disallowed(self):
        store = ConfigStore()
        store.set(make_flag(), env="dev", allow_overwrite=False)
        with pytest.raises(InvalidFlagConfigError):
            store.set(make_flag(), env="dev", allow_overwrite=False)


class TestVersionAndListeners:
    def test_version_increments_on_set(self):
        store = ConfigStore()
        assert store.version == 0
        store.set(make_flag(), env="dev")
        assert store.version == 1
        store.set(make_flag(name="other-flag"), env="dev")
        assert store.version == 2

    def test_listener_called_on_set(self):
        store = ConfigStore()
        calls = []
        store.register_listener(lambda: calls.append(1))

        store.set(make_flag(), env="dev")

        assert len(calls) == 1

    def test_multiple_listeners_all_called(self):
        store = ConfigStore()
        calls_a, calls_b = [], []
        store.register_listener(lambda: calls_a.append(1))
        store.register_listener(lambda: calls_b.append(1))

        store.set(make_flag(), env="dev")

        assert len(calls_a) == 1
        assert len(calls_b) == 1

    def test_get_raises_on_empty_env(self):
        store = ConfigStore()
        with pytest.raises(InvalidFlagConfigError):
            store.get("checkout-v2", env="")
