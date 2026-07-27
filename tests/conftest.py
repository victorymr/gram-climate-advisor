"""Shared pytest setup: make `src` importable and run from the project root so the
data-loading helpers' relative 'data/...' paths resolve."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
