"""One-command TradingAgents activation: build the framework's isolated venv.

Kevin asked for the startup code in one place (2026-11-01). The framework
lives in its own venv (feed spec §8) at TRADEHUB_AGENTS_PYTHON's location --
on the VPS that is /cache/agents-venv/bin/python, on the persistent cache
volume, so the build survives container recreates. Run INSIDE the tradehub
container (or anywhere the env vars point):

    python -m tradehub.scripts.setup_agents

Idempotent: a venv whose interpreter already imports the framework is left
alone. Ends by printing the first debate command. Keys are NOT handled here
-- GEMINI_API_KEY / GOOGLE_API_KEY arrive through the stack env.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parent.parent / "agents" / "requirements.txt"
DEFAULT_VENV_PYTHON = "/cache/agents-venv/bin/python"


def venv_python() -> Path:
    return Path(os.environ.get("TRADEHUB_AGENTS_PYTHON", DEFAULT_VENV_PYTHON))


def _run(cmd: list[str], run=subprocess.run) -> None:
    print("+", " ".join(cmd), flush=True)
    run(cmd, check=True)


def _imports_framework(python: Path, run=subprocess.run) -> bool:
    if not python.exists():
        return False
    result = run([str(python), "-c", "import tradingagents"], capture_output=True)
    return result.returncode == 0


def setup(run=subprocess.run) -> Path:
    python = venv_python()
    venv_dir = python.parent.parent
    if _imports_framework(python, run):
        print(f"TradingAgents venv already healthy at {venv_dir} -- nothing to build.")
        return python
    _run([sys.executable, "-m", "venv", str(venv_dir)], run)
    _run([str(python), "-m", "pip", "install", "--upgrade", "pip"], run)
    _run([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)], run)
    if not _imports_framework(python, run):
        raise SystemExit(f"venv built at {venv_dir} but `import tradingagents` still fails -- "
                         "see the pip output above.")
    print(f"TradingAgents venv ready at {venv_dir}.")
    return python


def main() -> int:
    setup()
    print("First debate:  python -m tradehub.scripts.agent_debate run NVDA")
    print("Keys needed in the stack env: GEMINI_API_KEY and GOOGLE_API_KEY (same value).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
