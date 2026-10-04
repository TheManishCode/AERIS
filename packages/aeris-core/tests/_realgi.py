"""Import this before any `gi` import that must reach the real bindings.

Two separate problems, one place.

**The typelib.** gtk4-layer-shell usually lands under ~/.local rather than the
system girepository directory, so `gi.require_version("Gtk4LayerShell", ...)`
fails unless GI_TYPELIB_PATH points at it.

**The stub.** test_manipulate installs a fake `gi` into the shared module
table so it can run without GTK, and under `unittest discover` that fake
outlives its own file. A module importing against it does not merely fail —
it raises ImportError, hits the `except` that every GTK test file has, and
*skips*. The suite stays green with the tests silently not running.

This is why the drop cannot live in conftest alone: conftest runs once, before
collection, and the stub is installed later, when test_manipulate is imported.
Every file that needs the real bindings has to re-check at its own import
time:

    from _realgi import use_real_gi
    use_real_gi()

Called, not merely imported. A module body runs once however many files import
it, so doing this work at import time would have protected only whichever file
imported it first — which `pytest test_manipulate.py test_navigate.py` proved
immediately.
"""

import os
import sys
from pathlib import Path


def use_real_gi() -> None:
    for name in [m for m in list(sys.modules) if m == "gi" or m.startswith("gi.")]:
        # A real module has a __file__; a stub does not.
        if getattr(sys.modules[name], "__file__", None) is None:
            del sys.modules[name]

    if "Gtk4LayerShell-1.0.typelib" in os.environ.get("GI_TYPELIB_PATH", ""):
        return
    for libdir in (Path.home() / ".local/lib", Path("/usr/lib"), Path("/usr/lib64")):
        if (libdir / "girepository-1.0/Gtk4LayerShell-1.0.typelib").exists():
            existing = os.environ.get("GI_TYPELIB_PATH")
            os.environ["GI_TYPELIB_PATH"] = str(libdir / "girepository-1.0") + (
                f":{existing}" if existing else ""
            )
            return
