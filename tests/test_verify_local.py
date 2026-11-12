"""Verification tooling only; no broker, terminal, or service startup."""
import json
import os
import subprocess
import sys

import pytest


def runner():
    from scripts import verify_local
    return verify_local


def test_environment_removes_runtime_overrides_without_mutating_parent(tmp_path):
    module = runner()
    original = {"PATH": os.defpath, "NO7_DB_PATH": "private-db", "mt5_password": "private",
                "NO7_REDIS_URL": "private", "KEEP": "yes"}
    env = module.child_environment(original, tmp_path / "tools" / "node.exe")
    assert original["NO7_DB_PATH"] == "private-db"
    assert not any(k.upper().startswith(("NO7_", "MT5_")) for k in env)
    assert env["KEEP"] == "yes"
    assert env["PATH"].split(os.pathsep)[0] == str(tmp_path / "tools")


def test_explicit_tool_is_not_silently_replaced(tmp_path):
    with pytest.raises(FileNotFoundError):
        runner().resolve_tool("node", str(tmp_path / "missing.exe"), {})


def test_explicit_tool_with_spaces_is_returned_as_absolute_path(tmp_path):
    tool = tmp_path / "tool folder" / "node.exe"
    tool.parent.mkdir()
    tool.write_bytes(b"fixture")
    assert runner().resolve_tool("node", str(tool), {}) == str(tool.resolve())


def test_junit_reports_dependency_policy_and_unclassified_skips(tmp_path):
    xml = tmp_path / "tests.xml"
    xml.write_text('<testsuites><testsuite tests="4" failures="0" errors="0" skipped="3">'
                   '<testcase name="ok"/><testcase name="redis"><skipped message="no redis-server binary"/></testcase>'
                   '<testcase name="source"><skipped message="sourced, never executed directly"/></testcase>'
                   '<testcase name="unknown"><skipped message="unfamiliar reason"/></testcase>'
                   '</testsuite></testsuites>', encoding="utf-8")
    report = runner().junit_report(xml)
    assert report["tests"] == 4
    assert report["skipped"] == 3
    assert {s["category"] for s in report["skip_reasons"]} == {"dependency", "policy", "unclassified"}
    assert sum(s["count"] for s in report["skip_reasons"]) == 3


def test_invalid_or_missing_junit_is_not_empty_success(tmp_path):
    with pytest.raises(FileNotFoundError):
        runner().junit_report(tmp_path / "absent.xml")
    xml = tmp_path / "bad.xml"
    xml.write_text("<testsuites/>")
    with pytest.raises(ValueError):
        runner().junit_report(xml)


@pytest.mark.parametrize("code,status", [(0, "passed"), (2, "failed")])
def test_real_child_exit_and_artifacts(tmp_path, code, status):
    outcome = runner().run_job("child", [sys.executable, "-c", f"print('evidence'); raise SystemExit({code})"],
                               tmp_path, dict(os.environ), tmp_path, 30)
    assert outcome["status"] == status
    assert outcome["exit_code"] == code
    assert (tmp_path / "child.exit").read_text() == str(code)
    assert "evidence" in (tmp_path / "child.log").read_text()


def test_timeout_has_terminal_artifact_not_stale_zero(tmp_path, monkeypatch):
    module = runner()

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", timeout)
    outcome = module.run_job("timeout", [sys.executable], tmp_path, {}, tmp_path, 1)
    assert outcome["status"] == "timeout"
    assert outcome["exit_code"] is None
    assert (tmp_path / "timeout.exit").read_text() == "TIMEOUT"


def test_missing_executable_is_error_not_pass(tmp_path):
    outcome = runner().run_job("missing", [str(tmp_path / "absent-tool")], tmp_path, {}, tmp_path, 1)
    assert outcome["status"] == "error"
    assert (tmp_path / "missing.exit").read_text() == "ERROR"


def test_result_with_skips_is_explicitly_qualified():
    module = runner()
    assert module.overall_status([{"status": "passed"}], {"skipped": 1}) == "passed_with_skips"
    assert module.overall_status([{"status": "timeout"}], {"skipped": 0}) == "failed"
    assert module.overall_status([{"status": "passed"}], {"skipped": 0}) == "passed"


def test_existing_artifact_directory_is_never_overwritten(tmp_path):
    folder = tmp_path / "evidence"
    folder.mkdir()
    sentinel = folder / "summary.json"
    sentinel.write_text("prior evidence")
    assert runner().main(["--output", str(folder)]) != 0
    assert sentinel.read_text() == "prior evidence"


def test_preflight_failure_writes_summary_without_secret_values(tmp_path):
    output = tmp_path / "run"
    code = runner().main(["--output", str(output), "--node", str(tmp_path / "missing")])
    summary = json.loads((output / "summary.json").read_text())
    assert code != 0
    assert summary["status"] == "blocked"
    assert summary["jobs"] == []
    assert "environment" not in summary