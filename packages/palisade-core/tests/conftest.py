"""Shared test setup.

Puts the package under test on the path, and makes sure the real `gi`
bindings are reachable before anything imports the UI — see `_realgi` for why
that is two separate problems and why one of them has to be re-checked by
every GTK test file rather than solved once here.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()
