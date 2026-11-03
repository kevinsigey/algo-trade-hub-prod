"""Screening Lab — composable screening-function library for the Algo Trade Hub.

Layers:
  sources.DataStore  — data layer (yfinance / SEC EDGAR / FRED / local files),
                       cached, with per-field provenance and explicit missing
                       reasons (never a silent zero).
  functions          — the registered function library (see catalog.json).
  spec               — query-spec validation (JSON Schema + catalog checks).
  runner             — executes a spec into a tidy table + provenance footer.
"""

from .sources import DataStore
from .functions import REGISTRY, get_function
from .spec import validate_spec, SpecError
from .runner import run_spec, RunResult

__all__ = ["DataStore", "REGISTRY", "get_function", "validate_spec",
           "SpecError", "run_spec", "RunResult"]
