"""Pytest-Bootstrap fürs Backend.

Stellt sicher, dass ``app`` importierbar ist — egal von wo pytest gestartet
wird (die Tests liegen in ``tests/`` ohne ``__init__.py``, daher landet sonst
nur ``backend/tests`` auf dem Pfad, nicht ``backend`` selbst).
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
