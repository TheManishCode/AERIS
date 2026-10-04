"""Make this package importable, and say so clearly when core is missing.

`aeris` (core) is a declared dependency, so in an installed environment it
is simply importable. Running the tests straight out of a clone it is not —
and in the monorepo it sits beside us rather than in site-packages. Both cases
are handled here so the suite runs with no PYTHONPATH incantation, and neither
makes this package depend on the other two modules.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

try:  # installed, or already on the path
    import aeris  # noqa: F401
except ImportError:
    sibling = ROOT.parent / "aeris-core" / "src"   # the monorepo layout
    if sibling.is_dir():
        sys.path.insert(1, str(sibling))
    else:
        # A bare ModuleNotFoundError thirty lines into a pytest traceback is a
        # poor answer to "I cloned this and ran the tests".
        pytest.exit(
            "aeris-core is not installed.\n"
            "  It is this package's one dependency. Install it with:\n"
            "    ./install.sh\n"
            "  or, for tests only:\n"
            "    pip install --user 'aeris-core @ "
            "git+https://github.com/TheManishCode/AERIS'",
            returncode=1,
        )
