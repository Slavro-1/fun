#!/usr/bin/env python3
"""Compatibility entry point for the terminal renderer."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fun_app.renderers.half_block import Encoder
from fun_app.renderers.kitty import KittyGraphics, _gfx_size, make_gfx_scene
from fun_app.renderers.playback import main
from fun_app.scenes.base import make_scene
from fun_app.scenes.registry import ALIASES, SCENES


if __name__ == '__main__':
    sys.exit(main())
