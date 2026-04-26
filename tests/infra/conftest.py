"""Add scripts/ to sys.path so tests can import configure directly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
