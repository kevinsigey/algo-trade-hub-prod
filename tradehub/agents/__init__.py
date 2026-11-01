"""The TradingAgents debate feed (spec docs/TradingAgents-Ideas-Feed-Spec.md, phase-2 §3.2).

On-demand, per-ticker LLM debate memos for the Ideas record -- qualitative annotations,
graded after the fact, and fenced: this package never imports order, broker or portfolio
code and nothing in the order path imports it. The framework itself runs in its own
environment (a subprocess, see runner.py); this package owns the artifact schema, the
store, the importer, the grader and the feed payload.
"""
