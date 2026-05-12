"""Launcher entry point for the city demo.

The shim runner expects a single .py file, not a package directory.
This stub re-exports main() from the `city` package so:

    python -m pdeck_sim.runner lib/city_app.py

works. On the deck itself you can launch either `city` (the package)
or `city_app` (this stub) - both work.

The sys.modules dance makes F5 reload pick up changes in city/*.py too,
not just this stub file.
"""
import sys
_to_clear = [m for m in sys.modules if m == 'city' or m.startswith('city.')]
for _m in _to_clear:
  del sys.modules[_m]

from city import main