"""Shipped-defaults refresh and export for portal config.

Run from the project folder:
    uv run pytest tests/test_config_sync.py -v

Uses temp folders only; the real AppData folder is never touched.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config_sync, utils  # noqa: E402

KINDS = {
    "field_mapping": "field_mapping.json",
    "doc_mapping": "doc_mapping.json",
    "automation_defaults": "automation_defaults.json",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    shipped = tmp_path / "shipped"
    saved = tmp_path / "saved"
    shipped.mkdir()
    saved.mkdir()

    def paths(kind):
        return {"default": str(shipped / KINDS[kind]), "user": str(saved / KINDS[kind])}

    monkeypatch.setattr(utils, "field_mapping_paths", lambda portal_id=None: paths("field_mapping"))
    monkeypatch.setattr(utils, "doc_mapping_paths", lambda portal_id=None: paths("doc_mapping"))
    monkeypatch.setattr(utils, "automation_defaults_paths", lambda portal_id=None: paths("automation_defaults"))
    monkeypatch.setattr(utils, "is_frozen", lambda: False)

    def write(folder, name, data):
        (folder / name).write_text(json.dumps(data), encoding="utf-8")

    write(shipped, "field_mapping.json", {"claim_no": {"search_labels": ["Claim No."], "col_offset": 1}})
    write(shipped, "doc_mapping.json", {"claim_documents_tab": {"Chassis": ["chassis"]}})
    write(shipped, "automation_defaults.json", {"plastic_depreciation_pct": "50"})
    return {
        "shipped": shipped, "saved": saved, "write": write,
        "state": str(tmp_path / "state.json"), "backup": str(tmp_path / "backup"),
    }


def _refresh(env):
    return config_sync.refresh_saved_config(["newindia"], state_path=env["state"], backup_root=env["backup"])


def test_first_launch_moves_saved_copies_to_backup_and_uses_shipped_defaults(env):
    env["write"](env["saved"], "automation_defaults.json", {"plastic_depreciation_pct": "40"})
    assert _refresh(env) == ["newindia"]
    assert not (env["saved"] / "automation_defaults.json").exists()
    assert utils.load_automation_defaults()["plastic_depreciation_pct"] == "50"
    backups = list(Path(env["backup"]).rglob("automation_defaults.json"))
    assert len(backups) == 1 and json.loads(backups[0].read_text())["plastic_depreciation_pct"] == "40"


def test_unchanged_defaults_keep_the_saved_settings(env):
    _refresh(env)
    env["write"](env["saved"], "automation_defaults.json", {"plastic_depreciation_pct": "40"})
    assert _refresh(env) == []
    assert utils.load_automation_defaults()["plastic_depreciation_pct"] == "40"


def test_changed_shipped_defaults_replace_saved_settings_again(env):
    _refresh(env)
    env["write"](env["saved"], "automation_defaults.json", {"plastic_depreciation_pct": "40"})
    env["write"](env["shipped"], "automation_defaults.json", {"plastic_depreciation_pct": "45"})
    assert _refresh(env) == ["newindia"]
    assert utils.load_automation_defaults()["plastic_depreciation_pct"] == "45"


def test_fresh_pc_has_nothing_to_replace(env):
    assert _refresh(env) == []
    assert json.loads(Path(env["state"]).read_text())["newindia"]


def test_spacing_changes_alone_do_not_count_as_new_defaults(env):
    _refresh(env)
    env["write"](env["saved"], "automation_defaults.json", {"plastic_depreciation_pct": "40"})
    data = json.loads((env["shipped"] / "automation_defaults.json").read_text())
    (env["shipped"] / "automation_defaults.json").write_text(json.dumps(data, indent=4) + "\r\n", encoding="utf-8")
    assert _refresh(env) == []


def test_export_writes_the_effective_config_into_the_shipped_files(env):
    env["write"](env["saved"], "automation_defaults.json", {"plastic_depreciation_pct": "40"})
    env["write"](env["saved"], "field_mapping.json",
                 {"claim_no": {"search_labels": ["Claim No.", "Claim #"]}, "metal": {"col_offset": -1}})
    written = config_sync.export_to_project("newindia", state_path=env["state"])
    assert {Path(p).name for p in written} == set(KINDS.values())
    shipped = json.loads((env["shipped"] / "automation_defaults.json").read_text())
    assert shipped["plastic_depreciation_pct"] == "40"
    mapping = json.loads((env["shipped"] / "field_mapping.json").read_text())
    assert mapping["claim_no"]["search_labels"] == ["Claim No.", "Claim #"]
    assert mapping["claim_no"]["col_offset"] == 1  # shipped value kept where the PC did not change it
    assert mapping["metal"] == {"col_offset": -1}
    assert 'search_labels": ["Claim No.", "Claim #"]' in (env["shipped"] / "field_mapping.json").read_text()


def test_export_does_not_make_this_pc_refresh_itself(env):
    env["write"](env["saved"], "automation_defaults.json", {"plastic_depreciation_pct": "40"})
    config_sync.export_to_project("newindia", state_path=env["state"])
    assert _refresh(env) == []
    assert utils.load_automation_defaults()["plastic_depreciation_pct"] == "40"


def test_export_refuses_private_keys_and_writes_nothing(env):
    env["write"](env["saved"], "automation_defaults.json", {"password": "x"})
    before = (env["shipped"] / "automation_defaults.json").read_text()
    with pytest.raises(ValueError, match="password"):
        config_sync.export_to_project("newindia", state_path=env["state"])
    assert (env["shipped"] / "automation_defaults.json").read_text() == before
    assert not (env["shipped"] / "field_mapping.json").read_text().startswith("{\n")


def test_export_is_refused_in_a_packaged_exe(env, monkeypatch):
    monkeypatch.setattr(utils, "is_frozen", lambda: True)
    with pytest.raises(RuntimeError, match="project folder"):
        config_sync.export_to_project("newindia", state_path=env["state"])


def test_runs_from_the_project_folder_never_refresh_saved_settings(env, monkeypatch):
    monkeypatch.setattr(utils, "is_frozen", lambda: False)
    monkeypatch.setattr(
        config_sync, "refresh_saved_config",
        lambda *a, **k: pytest.fail("a source run must not refresh saved settings"),
    )
    assert config_sync.refresh_saved_config_for_all_portals() == []


def test_packaged_exe_refreshes_every_registered_portal(env, monkeypatch):
    monkeypatch.setattr(utils, "is_frozen", lambda: True)
    seen = []
    monkeypatch.setattr(config_sync, "refresh_saved_config", lambda ids, **k: seen.extend(ids) or list(seen))
    config_sync.refresh_saved_config_for_all_portals()
    assert {"uiic", "newindia", "oic"} <= set(seen)


def test_dump_round_trips_and_keeps_lists_inline_when_asked():
    document = {"a": {"labels": ["x", "y"], "n": 1, "flag": True, "none": None}, "b": [{"k": "v"}], "c": []}
    for inline in (True, False):
        assert json.loads(config_sync._dumps(document, inline_lists=inline)) == document
    assert '"labels": ["x", "y"]' in config_sync._dumps(document, inline_lists=True)
    assert '"labels": [\n' in config_sync._dumps(document, inline_lists=False)
