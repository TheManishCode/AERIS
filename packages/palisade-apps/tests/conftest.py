"""Make this package importable from a checkout.

`palisade` (core) is a declared dependency, so in an installed environment it
is simply importable. Running the tests straight out of a clone of this repo
alone, it is not — and in the monorepo it sits beside us rather than in
site-packages. Both cases are handled here so the suite runs with no
PYTHONPATH incantation, and neither makes this package depend on the other
two modules.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

try:  # installed, or already on the path
    import palisade  # noqa: F401
except ImportError:  # pragma: no cover - checkout layout only
    sibling = ROOT.parent / "palisade-core" / "src"
    if sibling.is_dir():
        sys.path.insert(1, str(sibling))
