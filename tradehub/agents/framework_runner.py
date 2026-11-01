"""Runs INSIDE the framework's own environment (never imported by the hub): builds the
TradingAgents graph for one ticker and prints one JSON object with the raw final state.
The hub side (runner.py) spawns it with the isolated env's interpreter and imports the
JSON tolerantly -- framework formats drift; nothing here is trusted to be complete.

Usage: python framework_runner.py <TICKER> <YYYY-MM-DD>
Env: TRADEHUB_AGENTS_PROVIDER (default anthropic), TRADEHUB_AGENTS_MODEL
     (default claude-sonnet-4-5), plus the provider's own API key variables.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    ticker, as_of = sys.argv[1].upper(), sys.argv[2]
    provider = os.getenv("TRADEHUB_AGENTS_PROVIDER", "anthropic")
    model = os.getenv("TRADEHUB_AGENTS_MODEL", "claude-sonnet-4-5")
    try:
        import importlib.metadata

        version = importlib.metadata.version("tradingagents")
    except Exception:  # noqa: BLE001
        version = None
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = dict(DEFAULT_CONFIG)
    config.update({"llm_provider": provider, "deep_think_llm": model, "quick_think_llm": model,
                   "max_debate_rounds": 1, "max_risk_discuss_rounds": 1})
    graph = TradingAgentsGraph(debug=False, config=config)
    state, decision = graph.propagate(ticker, as_of)
    # The state holds the debate's working dicts; keep only JSON-safe text fields.
    safe_state = {}
    for key, value in dict(state).items():
        if isinstance(value, str):
            safe_state[key] = value
        elif isinstance(value, dict):
            safe_state[key] = {k: v for k, v in value.items() if isinstance(v, str)}
    print(json.dumps({"ticker": ticker, "decision": decision if isinstance(decision, str) else None,
                      "final_state": safe_state, "framework_version": version,
                      "llm_provider": provider, "llm_model": model,
                      "inputs_note": "framework defaults: market, social, news and fundamentals "
                                     "analysts via the framework's own vendors",
                      "cost_usd": None}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
