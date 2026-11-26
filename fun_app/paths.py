"""Locate the launchers in a checkout or installed prefix."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'extras.py'
COMMANDS = ROOT if (ROOT / 'fun').is_file() else ROOT.parents[1] / 'bin'
