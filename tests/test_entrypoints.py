import importlib


def test_daemon_and_approve_mains_exist():
    daemon = importlib.import_module("cc_poke.daemon")
    approve = importlib.import_module("cc_poke.approve")
    assert callable(daemon.main)
    assert callable(approve.main)
