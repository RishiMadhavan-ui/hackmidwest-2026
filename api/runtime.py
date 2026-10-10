"""Import the one shared source tree until Cameron's package metadata lands."""

import sys
from pathlib import Path

SHARED_ROOT = Path(__file__).resolve().parent.parent / "shared"
if str(SHARED_ROOT) not in sys.path:
  sys.path.insert(0, str(SHARED_ROOT))
