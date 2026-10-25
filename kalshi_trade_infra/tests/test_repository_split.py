"""repository.py is being split per aggregate (ARCHITECTURE.md step 6); old import paths must keep working."""
import importlib
import inspect
import pkgutil

import app.adapters.db as db
from app import repository as repo

MODULES = [importlib.import_module("app.adapters.db." + m.name) for m in pkgutil.iter_modules(db.__path__)]


def test_every_moved_function_is_reexported_from_app_repository():
    assert len(MODULES) >= 3
    for module in MODULES:
        for name, fn in inspect.getmembers(module, inspect.isfunction):
            if fn.__module__ == module.__name__:
                assert getattr(repo, name) is fn, "%s.%s" % (module.__name__, name)


def test_split_modules_never_import_the_legacy_facade():
    for module in MODULES:
        assert "app.repository" not in inspect.getsource(module), module.__name__
