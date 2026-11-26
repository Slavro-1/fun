"""Compatibility module for the installed fun_settings.py path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fun_app.settings import *


if __name__ == '__main__':
    main()
