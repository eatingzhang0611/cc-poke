import threading
import time

from cc_poke.store import DecisionStore


def test_register_returns_unique_unguessable_ids():
    s = DecisionStore()
    a, b = s.register(), s.register()
    assert a != b
    assert len(a) > 20


def test_resolve_then_wait_returns_decision():
    s = DecisionStore()
    rid = s.register()
    assert s.resolve(rid, "allow") is True
    assert s.wait(rid, 1.0) == "allow"


def test_wait_blocks_until_resolved():
    s = DecisionStore()
    rid = s.register()

    def later():
        time.sleep(0.05)
        s.resolve(rid, "deny")

    threading.Thread(target=later).start()
    assert s.wait(rid, 2.0) == "deny"


def test_wait_times_out_returns_none():
    s = DecisionStore()
    rid = s.register()
    assert s.wait(rid, 0.05) is None


def test_resolve_unknown_id_returns_false():
    assert DecisionStore().resolve("nope", "allow") is False


def test_resolve_is_one_shot():
    s = DecisionStore()
    rid = s.register()
    assert s.resolve(rid, "allow") is True
    assert s.resolve(rid, "deny") is False
    assert s.wait(rid, 1.0) == "allow"


def test_wait_consumes_id():
    s = DecisionStore()
    rid = s.register()
    s.resolve(rid, "allow")
    assert s.wait(rid, 1.0) == "allow"
    # consumed: a second resolve sees an unknown id
    assert s.resolve(rid, "deny") is False


def test_cancel_makes_wait_return_none():
    s = DecisionStore()
    rid = s.register()
    s.cancel(rid)
    assert s.wait(rid, 0.05) is None
