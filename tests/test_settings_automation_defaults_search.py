"""Offscreen Qt tests for the Automation Defaults search bar across all portals."""

import os

import pytest


def _make_settings_page(monkeypatch, tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)
    from PyQt6.QtWidgets import QApplication

    import app.ui.components.settings_page as sp_mod

    app = QApplication.instance() or QApplication([])  # noqa: F841

    stores = {
        "settings": {
            "uiic": {"username": "u", "password": "p", "portal_url": "https://example.invalid/uiic"},
            "newindia": {"username": "u", "password": "p", "portal_url": "https://example.invalid/nia"},
            "oic": {"username": "u", "password": "p", "portal_url": "https://example.invalid/oic"},
        },
        "defaults": {
            "uiic": {
                "remarks_default": "Ok",
                "observation_default": "Verified",
                "printable_print_mode": "scale_percentage",
                "printable_scale_percentage": 80,
                "printable_column_range": "A:L",
            },
            "newindia": {
                "survey_completed": "Yes",
                "remarks_default": "Ok",
                "hsn_code": "8512",
                "table_boundary_keyword": "sub total|grand total",
                "printable_print_mode": "column_range",
                "printable_scale_percentage": 85,
                "printable_column_range": "A:L",
            },
            "oic": {
                "unknown_claim_type_default": "CASHLESS",
                "gst_type": "IGST",
                "upload_remarks": "Documents verified and uploaded.",
                "table_boundary_keyword": "sub total",
                "typing_delay_ms": 25,
                "printable_print_mode": "scale_percentage",
                "printable_scale_percentage": 90,
                "printable_column_range": "A:M",
            },
        },
        "field": {
            "uiic": {"claim_no": {"search_labels": ["Claim No"], "sheet": "ALL", "row_offset": 0, "col_offset": 1}},
            "newindia": {"claim_no": {"search_labels": ["Claim No"], "sheet": "ALL", "row_offset": 0, "col_offset": 1}},
            "oic": {"claim_no": {"search_labels": ["Claim No"], "sheet": "ALL", "row_offset": 0, "col_offset": 1}},
        },
        "doc": {
            "uiic": {"claim_documents_tab": {"rc": ["rc_book"]}, "claim_assessment_tab": {}},
            "newindia": {"claim_documents_tab": {"rc": ["rc_book"]}, "claim_assessment_tab": {}},
            "oic": {"claim_documents_tab": {"rc": ["rc_book"]}, "claim_assessment_tab": {}},
        },
    }

    monkeypatch.setattr(sp_mod, "load_settings", lambda portal_id="uiic": dict(stores["settings"][portal_id]))
    monkeypatch.setattr(sp_mod, "save_settings", lambda data, portal_id="uiic": stores["settings"].__setitem__(portal_id, dict(data)))
    monkeypatch.setattr(sp_mod, "load_automation_defaults", lambda portal_id="uiic": dict(stores["defaults"][portal_id]))
    monkeypatch.setattr(sp_mod, "save_automation_defaults", lambda data, portal_id="uiic": stores["defaults"].__setitem__(portal_id, dict(data)))
    monkeypatch.setattr(sp_mod, "load_field_mapping", lambda portal_id="uiic": dict(stores["field"][portal_id]))
    monkeypatch.setattr(sp_mod, "save_field_mapping", lambda data, portal_id="uiic": stores["field"].__setitem__(portal_id, dict(data)))
    monkeypatch.setattr(sp_mod, "load_doc_mapping", lambda portal_id="uiic": dict(stores["doc"][portal_id]))
    monkeypatch.setattr(sp_mod, "save_doc_mapping", lambda data, portal_id="uiic": stores["doc"].__setitem__(portal_id, dict(data)))

    logs = []
    page = sp_mod.SettingsPage(append_log_cb=logs.append)
    return app, page, stores, logs


def _visible_keys(table):
    from PyQt6.QtCore import Qt

    keys = []
    for row in range(table.rowCount()):
        if not table.isRowHidden(row):
            item = table.item(row, 0)
            keys.append(item.data(Qt.ItemDataRole.UserRole))
    return keys


@pytest.mark.parametrize("portal_id", ["uiic", "newindia", "oic"])
def test_automation_defaults_search_filters_by_setting_value_and_used_in(monkeypatch, tmp_path, portal_id):
    _app, page, _, _ = _make_settings_page(monkeypatch, tmp_path)
    page.set_portal(portal_id)

    total_rows = page.defaults_table.rowCount()
    assert total_rows > 0
    assert len(_visible_keys(page.defaults_table)) == total_rows

    # Match Setting name and Used In together
    page.defaults_search_input.setText("Print Mode")
    assert _visible_keys(page.defaults_table) == [
        "printable_print_mode",
        "printable_scale_percentage",
        "printable_column_range",
    ]

    # Match Value (ComboBox display text and SpinBox integer) and Used In
    if portal_id == "newindia":
        page.defaults_search_input.setText("8512")
        assert _visible_keys(page.defaults_table) == ["hsn_code"]
        page.defaults_search_input.setText("Quick Update")
        assert "survey_completed" in _visible_keys(page.defaults_table)
        assert "hsn_code" not in _visible_keys(page.defaults_table)
    elif portal_id == "oic":
        page.defaults_search_input.setText("25")
        assert "typing_delay_ms" in _visible_keys(page.defaults_table)
        page.defaults_search_input.setText("Document Upload")
        assert _visible_keys(page.defaults_table) == ["upload_remarks"]
    else:
        page.defaults_search_input.setText("Observation Default")
        assert _visible_keys(page.defaults_table) == ["observation_default"]
        page.defaults_search_input.setText("Scale Percentage")
        assert _visible_keys(page.defaults_table) == [
            "printable_print_mode",
            "printable_scale_percentage",
        ]
        page.defaults_search_input.setText("Interim Report")
        assert _visible_keys(page.defaults_table) == ["remarks_default"]

    # Clear restores all rows
    page.defaults_search_input.clear()
    assert len(_visible_keys(page.defaults_table)) == total_rows


def test_automation_defaults_search_persists_across_portal_switch_and_saves_hidden_rows(monkeypatch, tmp_path):
    _app, page, stores, logs = _make_settings_page(monkeypatch, tmp_path)

    # Search persists across portal switches (same as Field Mapping)
    page.set_portal("newindia")
    page.defaults_search_input.setText("Scale Percentage")
    assert _visible_keys(page.defaults_table) == ["printable_scale_percentage"]

    page.set_portal("oic")
    assert page.defaults_search_input.text() == "Scale Percentage"
    assert _visible_keys(page.defaults_table) == [
        "printable_print_mode",
        "printable_scale_percentage",
    ]
    assert "upload_remarks" not in _visible_keys(page.defaults_table)

    # Save while filtered keeps both visible and hidden settings intact
    page.defaults_search_input.setText("Upload Remarks")
    assert _visible_keys(page.defaults_table) == ["upload_remarks"]
    for row in range(page.defaults_table.rowCount()):
        if not page.defaults_table.isRowHidden(row):
            page.defaults_table.cellWidget(row, 1).setText("Updated verified documents.")
            break

    page._save_all()
    assert stores["defaults"]["oic"]["upload_remarks"] == "Updated verified documents."
    assert stores["defaults"]["oic"]["gst_type"] == "IGST"
    assert stores["defaults"]["oic"]["typing_delay_ms"] == "25"
    assert any("Settings saved" in entry for entry in logs)


def test_save_error_on_hidden_default_clears_filter_to_reveal_row(monkeypatch, tmp_path):
    _app, page, stores, logs = _make_settings_page(monkeypatch, tmp_path)
    page.set_portal("oic")

    # Set upload_remarks to an invalid short string (< 10 chars), then hide it via search
    for row in range(page.defaults_table.rowCount()):
        item = page.defaults_table.item(row, 0)
        if item and item.data(0x0100) == "upload_remarks":
            page.defaults_table.cellWidget(row, 1).setText("short")
            break

    page.defaults_search_input.setText("GST Type")
    assert "upload_remarks" not in _visible_keys(page.defaults_table)

    page._save_all()

    assert page.defaults_search_input.text() == ""
    assert "upload_remarks" in _visible_keys(page.defaults_table)
    assert stores["defaults"]["oic"]["upload_remarks"] == "Documents verified and uploaded."
    assert any("Save failed" in entry for entry in logs)


def test_field_and_doc_mapping_search_still_work(monkeypatch, tmp_path):
    _app, page, _, _ = _make_settings_page(monkeypatch, tmp_path)
    page.set_portal("newindia")

    page.search_input.setText("claim_no")
    assert not page.mapping_table.isRowHidden(0)
    page.search_input.setText("nonexistent_field")
    assert page.mapping_table.isRowHidden(0)

    page.doc_search_input.setText("rc_book")
    assert not page.doc_table.isRowHidden(0)
    page.doc_search_input.setText("nonexistent_doc")
    assert page.doc_table.isRowHidden(0)
