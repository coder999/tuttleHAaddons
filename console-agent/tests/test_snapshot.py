"""The snapshot the add-on builds must satisfy the console's own contract file.

CONSOLE_SCHEMA points at the live schema in the console working copy rather
than a copy vendored here on purpose: a copy could not contradict itself, but
it also could not notice the console changing underneath us. If this test
starts failing because the file moved, set CONSOLE_SCHEMA rather than
snapshotting the schema into this repo.
"""
import json
import os
import pathlib

import jsonschema

from app import main
from tests.fake_supervisor import FakeSupervisor

SCHEMA = json.loads(pathlib.Path(os.environ.get("CONSOLE_SCHEMA", os.path.expanduser(
    "~/docker/html-local/console/htdocs/contract/snapshot.schema.json"))).read_text())


def validate(doc):
    jsonschema.Draft202012Validator(SCHEMA).validate(doc)


def test_snapshot_validates_against_contract():
    doc = main.build_snapshot(FakeSupervisor(), addon_stats=True, sample_seconds=0.05)
    validate(doc)
    assert doc["host"] == "ha" and doc["logs"] == {} and doc["timers"] == []


def test_metrics_shape_and_ranges():
    m = main.build_snapshot(FakeSupervisor(), addon_stats=True, sample_seconds=0.05)["metrics"]
    assert 0 <= m["cpu_pct"] <= 100 and m["mem_total_mb"] > 0 and m["uptime_s"] > 0
    assert m["disk_root_total_gb"] == 433.8 and m["disk_root_used_gb"] == 137.5


def test_addons_become_containers_with_stats_only_when_started():
    cs = {c["status"].split(" · ")[1]: c
          for c in main.build_snapshot(FakeSupervisor(), addon_stats=True, sample_seconds=0.05)["containers"]}
    assert cs["a0d7b954_glances"]["state"] == "started" and cs["a0d7b954_glances"]["cpu_pct"] == 0.44
    assert cs["local_stopped"]["state"] == "stopped" and "cpu_pct" not in cs["local_stopped"]
    assert cs["local_broken"]["state"] == "error"


def test_stats_are_only_requested_for_started_addons():
    sup = FakeSupervisor()
    main.build_snapshot(sup, addon_stats=True, sample_seconds=0.05)
    assert sup.stats_calls == ["a0d7b954_glances"]


def test_addon_stats_option_off_skips_the_stats_calls():
    sup = FakeSupervisor()
    doc = main.build_snapshot(sup, addon_stats=False, sample_seconds=0.05)
    assert sup.stats_calls == []
    assert all("cpu_pct" not in c for c in doc["containers"])


def test_kernel_string_carries_versions():
    assert main.build_snapshot(FakeSupervisor(), addon_stats=False, sample_seconds=0.05)["kernel"] \
        == "6.18.39-haos · HAOS 18.2 · Core 2026.9.1"


def test_supervisor_failure_degrades_not_raises():
    sup = FakeSupervisor(fail=True)
    doc = main.build_snapshot(sup, addon_stats=True, sample_seconds=0.05)
    validate(doc)
    assert doc["containers"] == [] and doc["metrics"]["disk_root_total_gb"] == 0


def test_push_logs_status_and_never_raises(monkeypatch, capsys):
    class R:  # requests.Response stand-in
        def __init__(self, code, text=""):
            self.status_code, self.text = code, text

    monkeypatch.setattr(main.requests, "post", lambda *a, **k: R(422, '{"errors":["/: bad"]}'))
    main.push("http://x/api/ingest", "t", b"{}")
    assert "422" in capsys.readouterr().out

    def boom(*a, **k):
        raise main.requests.ConnectionError("refused")

    monkeypatch.setattr(main.requests, "post", boom)
    main.push("http://x/api/ingest", "t", b"{}")   # must not raise
    assert "unreachable" in capsys.readouterr().out


def test_push_logs_the_happy_path(monkeypatch, capsys):
    class R:
        status_code, text = 204, ""

    monkeypatch.setattr(main.requests, "post", lambda *a, **k: R())
    main.push("http://x/api/ingest", "t", b"{}")
    assert "204" in capsys.readouterr().out


def test_missing_supervisor_token_exits_2(monkeypatch, capsys):
    """The Supervisor shows a non-zero exit as a failed add-on, which is the
    only way a user finds out hassio_api was never granted."""
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert main.main() == 2
    assert "SUPERVISOR_TOKEN" in capsys.readouterr().out
