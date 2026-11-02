"""The TradingAgents setup module: command sequence + the idempotent skip."""


from tradehub.scripts import setup_agents


class _Result:
    def __init__(self, returncode=0):
        self.returncode = returncode


def test_setup_builds_the_venv_and_installs_requirements(monkeypatch, tmp_path):
    python = tmp_path / "agents-venv" / "bin" / "python"
    monkeypatch.setenv("TRADEHUB_AGENTS_PYTHON", str(python))
    calls = []
    state = {"importable": False}

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[1:] == ["-c", "import tradingagents"]:
            return _Result(0 if state["importable"] else 1)
        if "-m" in cmd and "venv" in cmd:
            python.parent.mkdir(parents=True, exist_ok=True)
            python.touch()
        if "install" in cmd and "-r" in cmd:
            state["importable"] = True
        return _Result(0)

    setup_agents.setup(run=fake_run)
    verbs = [" ".join(c) for c in calls]
    assert any(" -m venv " in f" {v} " for v in verbs)
    assert any("pip" in v and "install" in v and "requirements.txt" in v for v in verbs)


def test_setup_skips_a_healthy_venv(monkeypatch, tmp_path, capsys):
    python = tmp_path / "agents-venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setenv("TRADEHUB_AGENTS_PYTHON", str(python))
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _Result(0)

    setup_agents.setup(run=fake_run)
    assert len(calls) == 1 and calls[0][1:] == ["-c", "import tradingagents"]
    assert "already healthy" in capsys.readouterr().out
