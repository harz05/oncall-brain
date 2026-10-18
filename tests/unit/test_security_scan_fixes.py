"""Fixes for the Claude Security scan of 6da2baa (CLAUDE-SECURITY-20261018-104619): F1 TLS hostname checking, F5 health
error categories, F6 terminal control characters, F8 the plugin launcher's import probe."""

import os
import subprocess
from pathlib import Path

from redis.exceptions import AuthenticationError, ConnectionError

from oncall_brain.adapters.falkordb.repository import FalkorGraphStore
from oncall_brain.api.app import _db_category
from scripts.headless import clean

ROOT = Path(__file__).resolve().parents[2]


def test_f1_tls_from_host_fields_checks_the_hostname(monkeypatch):
    from oncall_brain.adapters.falkordb import repository

    seen = {}
    monkeypatch.setattr(repository, "FalkorDB", lambda **kw: seen.update(kw))  # the real client connects at once
    FalkorGraphStore(host="db.example.invalid", port=6380, ssl=True)
    assert seen["ssl"] is True and seen["ssl_check_hostname"] is True


def test_f5_health_names_a_category_never_the_exception_text():
    secret = "Xk9pQ2"  # what a malformed FALKORDB_URL's ValueError would quote
    assert secret not in _db_category(ValueError(f"Port could not be cast to integer value as '{secret}'"))
    assert _db_category(AuthenticationError("invalid username-password pair")).startswith("authentication failed")
    assert _db_category(ConnectionError("Error 111 connecting to 10.0.0.5:6379")).startswith("connection refused")


def test_f6_control_characters_are_shown_escaped_not_run():
    out = clean("cause: x\x1b]0;owned\x07\x1b[2J\nnext line\tok")
    assert "\x1b" not in out and "\x07" not in out and "\\x1b" in out and "\nnext line\tok" in out


def test_f8_the_launcher_does_not_import_from_the_current_directory(tmp_path):
    (tmp_path / "oncall_brain").mkdir()
    planted = "import sys; print('PLANTED', file=sys.stderr); sys.exit(7)\n"
    (tmp_path / "oncall_brain" / "__init__.py").write_text(planted)
    env = {**os.environ, "ONCALL_BRAIN_HOME": str(ROOT), "ONCALL_BRAIN_PYTHON": os.environ.get("VIRTUAL_ENV", "") +
           "/bin/python"}
    probe = subprocess.run(["bash", "-c", "\"$ONCALL_BRAIN_PYTHON\" -P -c 'import oncall_brain, sys; "
                            "print(oncall_brain.__file__)'"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert probe.returncode == 0 and "PLANTED" not in probe.stderr and str(tmp_path) not in probe.stdout
    assert "-P -c 'import oncall_brain'" in (ROOT / "plugin/bin/oncall-brain-mcp").read_text()
