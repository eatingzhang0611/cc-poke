import importlib


def test_all_mains_exist():
    for mod_name in ("cc_poke.daemon", "cc_poke.approve", "cc_poke.notifier", "cc_poke.stopper"):
        mod = importlib.import_module(mod_name)
        assert callable(mod.main), f"{mod_name}.main not callable"
