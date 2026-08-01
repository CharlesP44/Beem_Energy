import importlib

from custom_components.beem_energy import beem_api


def setup_function():
    # Ensure a clean state before each test
    beem_api._global_429_reset()


def test_initial_not_locked(monkeypatch):
    monkeypatch.setattr(beem_api.time, "time", lambda: 1000)
    assert not beem_api._global_429_is_locked()
    assert beem_api._GLOBAL_429_RETRY == 0


def test_set_lock_and_release(monkeypatch):
    monkeypatch.setattr(beem_api.time, "time", lambda: 1000)
    beem_api._global_429_reset()
    beem_api._global_429_set_lock()
    # After first set, retry should be incremented and lock_ts set
    assert beem_api._GLOBAL_429_RETRY == 1
    assert beem_api._GLOBAL_429_LOCK_TS == 1000 + beem_api._GLOBAL_429_BASE
    assert beem_api._global_429_is_locked()

    # Advance time beyond lock expiration
    monkeypatch.setattr(beem_api.time, "time", lambda: 1000 + beem_api._GLOBAL_429_BASE + 1)
    assert not beem_api._global_429_is_locked()


def test_exponential_backoff_and_cap(monkeypatch):
    # Use a fixed time to make expected lock timestamps deterministic
    monkeypatch.setattr(beem_api.time, "time", lambda: 2000)
    beem_api._global_429_reset()

    expected_delays = [
        min(beem_api._GLOBAL_429_BASE * (2 ** i), beem_api._GLOBAL_429_MAX)
        for i in range(4)
    ]

    for expected in expected_delays:
        beem_api._global_429_set_lock()
        assert beem_api._GLOBAL_429_LOCK_TS == 2000 + expected

    # After reset, values return to defaults
    beem_api._global_429_reset()
    assert beem_api._GLOBAL_429_RETRY == 0
    assert beem_api._GLOBAL_429_LOCK_TS == 0.0
