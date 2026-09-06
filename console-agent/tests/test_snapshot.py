"""The snapshot the add-on builds must satisfy the console's own contract file.

CONSOLE_SCHEMA points at the live schema in the console working copy rather
than a copy vendored here on purpose: a copy could not notice the console
changing underneath us. Nothing runs these tests automatically, so this
validates against the console checkout's contract only when someone runs
pytest on nexus. If the file moves, set CONSOLE_SCHEMA rather than
snapshotting the schema into this repo.
"""
import json
import os
import pathlib

import jsonschema
import pytest

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


def test_network_throughput_is_reported_as_zero():
    """/proc/net/dev is namespaced and the add-on has no host_network, so any
    counter here would describe the add-on, not the host. The contract requires
    the keys, so send an honest zero rather than a plausible wrong number."""
    m = main.build_snapshot(FakeSupervisor(), addon_stats=False, sample_seconds=0.05)["metrics"]
    assert m["net_rx_bps"] == 0 and m["net_tx_bps"] == 0


def test_addons_become_containers_with_stats_only_when_started():
    cs = {c["status"].split(" · ")[-1]: c
          for c in main.build_snapshot(FakeSupervisor(), addon_stats=True, sample_seconds=0.05)["containers"]}
    assert cs["a0d7b954_glances"]["state"] == "started" and cs["a0d7b954_glances"]["cpu_pct"] == 0.44
    assert cs["local_stopped"]["state"] == "stopped" and "cpu_pct" not in cs["local_stopped"]
    assert cs["local_broken"]["state"] == "error"


def test_status_string_carries_the_addon_version():
    """The console's container table shows `status` but not `image`, so the
    version has to be repeated into `status` to be visible at all."""
    cs = {c["status"].split(" · ")[-1]: c
          for c in main.build_snapshot(FakeSupervisor(), addon_stats=False, sample_seconds=0.05)["containers"]}
    assert cs["a0d7b954_glances"]["status"] == "started · v0.22.1 · a0d7b954_glances"
    assert cs["local_stopped"]["status"] == "stopped · v3.1.0 · local_stopped"
    assert cs["a0d7b954_glances"]["image"] == "0.22.1"


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


SENTINEL = "s3cr3t-ha-ingest-token-never-log-me"


def _raise_connection_error(*a, **k):
    raise main.requests.ConnectionError("refused")


def test_push_never_logs_the_ingest_token(monkeypatch, capsys):
    """The add-on log is visible in the HA UI and gets pasted into issues, so
    the ingest token must not reach it on any branch."""
    class R:
        def __init__(self, code, text=""):
            self.status_code, self.text = code, text

    for responder in (lambda *a, **k: R(204),
                      lambda *a, **k: R(500, "internal error"),
                      _raise_connection_error):
        monkeypatch.setattr(main.requests, "post", responder)
        main.push("http://x/api/ingest", SENTINEL, b"{}")
        out = capsys.readouterr().out
        assert out.strip(), "each branch must log something"
        assert SENTINEL not in out


class _RaggedSupervisor:
    """Fields present-but-null and keys missing entirely. The real Supervisor
    should never send this, but a crash here would cost the whole snapshot,
    so the agent has to survive it."""

    def host_info(self):
        return {"operating_system": None, "kernel": None,
                "disk_total": None, "disk_used": None, "boot_timestamp": None}

    def core_info(self):
        return {}

    def addons(self):
        return [{"slug": "no_version"},
                {"name": "Named", "slug": "s2", "version": None, "state": None}]

    def addon_stats(self, slug):
        raise AssertionError("neither add-on is started; stats must not be requested")


def test_ragged_supervisor_payload_degrades_instead_of_crashing():
    doc = main.build_snapshot(_RaggedSupervisor(), addon_stats=True, sample_seconds=0.05)
    validate(doc)
    st = {c["status"].split(" · ")[-1]: c["status"] for c in doc["containers"]}
    assert st["no_version"] == "unknown · no_version"      # empty version -> no "v…" segment
    assert st["s2"] == "unknown · s2"
    assert doc["kernel"] == "unknown"
    assert doc["metrics"]["disk_root_total_gb"] == 0 and doc["metrics"]["uptime_s"] >= 0


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code, self._payload = status, payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise main.requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return {"data": self._payload}


def test_addons_falls_back_to_apps_on_404(monkeypatch):
    seen = []

    def fake_get(url, **k):
        seen.append(url)
        return _Resp(404) if url.endswith("/addons") else _Resp(200, {"apps": [{"slug": "x"}]})

    monkeypatch.setattr(main.requests, "get", fake_get)
    assert main.Supervisor("t").addons() == [{"slug": "x"}]
    assert seen == ["http://supervisor/addons", "http://supervisor/apps"]


def test_addons_reraises_non_404_instead_of_masking_it_with_apps(monkeypatch):
    """A 403 means hassio_role is wrong. Retrying /apps would replace that
    diagnosis with a second, less informative failure."""
    seen = []
    monkeypatch.setattr(main.requests, "get", lambda url, **k: (seen.append(url), _Resp(403))[1])
    with pytest.raises(main.requests.HTTPError) as ei:
        main.Supervisor("t").addons()
    assert "403" in str(ei.value)
    assert seen == ["http://supervisor/addons"]


@pytest.mark.parametrize("content", [None, "{not json", ""])
def test_unusable_options_file_exits_2(monkeypatch, tmp_path, capsys, content):
    """A corrupt or absent options file is a misconfiguration, not a transient
    fault, so exit non-zero and let the Supervisor show the add-on as failed."""
    monkeypatch.setenv("SUPERVISOR_TOKEN", "x")
    path = tmp_path / "options.json"
    if content is not None:
        path.write_text(content)
    monkeypatch.setattr(main, "OPTIONS", str(path))
    assert main.main() == 2
    out = capsys.readouterr().out
    assert "cannot read" in out and "not starting" in out
