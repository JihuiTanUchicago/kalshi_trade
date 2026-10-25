"""repository.py is being split per aggregate (ARCHITECTURE.md step 6); old import paths must keep working."""
import inspect

from app import repository as repo
from app.adapters.db import community_repository, sql


def test_every_moved_function_is_reexported_from_app_repository():
    for module in (community_repository, sql):
        for name, fn in inspect.getmembers(module, inspect.isfunction):
            if fn.__module__ == module.__name__:
                assert getattr(repo, name) is fn, name


def test_split_modules_never_import_the_legacy_facade():
    for module in (community_repository, sql):
        assert "app.repository" not in inspect.getsource(module)
