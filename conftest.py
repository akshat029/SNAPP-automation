"""Configure test path to find project modules."""
import sys
from pathlib import Path

# Add project root to sys.path so tests can import helpers, smartsheet_reader, etc.
sys.path.insert(0, str(Path(__file__).resolve().parent))
