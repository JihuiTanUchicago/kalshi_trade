"""repository.py is being split per aggregate (ARCHITECTURE.md step 6); old import paths must keep working."""
import importlib
import inspect
import pkgutil
import re
from pathlib import Path

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


def test_no_test_freezes_a_moved_function_through_the_facade():
    """Moved functions bind now_utc from app.adapters.db.sql, so patching repo.now_utc silently
    stops steering them (it still steers what is left in repository.py). A test that patches the
    facade clock must not call a moved function that reads the clock; patch the defining module
    instead (see app/adapters/db/sql.py). Indirect calls are not traced: check them when moving."""
    clocked = {name for module in MODULES for name, fn in inspect.getmembers(module, inspect.isfunction)
               if fn.__module__ == module.__name__ and "now_utc(" in inspect.getsource(fn)}
    alias = re.compile(r"from app import repository as (\w+)|import app\.repository as (\w+)")
    offenders = []
    for path in Path(__file__).parent.glob("test_*.py"):
        src = path.read_text()
        for n in {a or b for a, b in alias.findall(src)}:
            if re.search(r"setattr\(\s*%s\s*,\s*[\"']now_utc[\"']" % n, src):
                offenders += ["%s: %s" % (path.name, f) for f in sorted(clocked)
                              if re.search(r"\b%s\.%s\(" % (n, f), src)]
    assert offenders == [], offenders
