"""Phase 2 conftest template - copy this into your phase2/conftest.py.

Purpose: redirect imports like `from lru_cache import LRUCache` away from the
starter's compiled .pyc bundle and toward your own src/ where you're fixing
bugs. Pytest sees this conftest (which sits inside phase2/) before it sees
the parent one at `assignments/a3-testing/conftest.py`, and this one's
sys.path.insert(0, ...) puts src/ ahead in the search order.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))
