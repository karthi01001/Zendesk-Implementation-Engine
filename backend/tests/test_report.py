from __future__ import annotations

import io
import zipfile

from tests.factories import make_snapshot, sample_instance
from zie.report import Report, build_report, render_docx, render_html, report_filename


def _report() -> Report:
    areas = sample_instance()
    areas["triggers"].append({"id": 802, "title": "Old <script>", "active": False})
    return build_report(make_snapshot(areas, unavailable=("custom-roles",)))


def test_summary_counts_active_and_inactive() -> None:
    report = _report()
    triggers = next(r for r in report.summary if r.area == "Triggers")
    assert (triggers.items, triggers.active, triggers.inactive) == (2, 1, 1)
    roles = next(r for r in report.summary if r.area == "Custom roles")
    assert roles.status == "Not available"
    schedules = next(r for r in report.summary if r.area == "Schedules")
    assert schedules.active is None


def test_findings_cover_unused_fields_broken_refs_and_inactive_rules() -> None:
    titles = [f.title for f in _report().findings]
    assert titles[0] == "2 custom ticket fields are not used"
    assert titles[1] == "1 reference points at an item that no longer exists"
    assert titles[2] == "Inactive business rules"


def test_area_tables_have_area_specific_columns() -> None:
    report = _report()
    triggers = next(a for a in report.areas if a.key == "triggers")
    assert triggers.columns == [
        "Name",
        "Category",
        "Conditions",
        "Actions",
        "Active",
        "Updated",
        "ID",
    ]
    assert triggers.rows[0][:5] == ["Route shoe tickets", "Routing", "3", "5", "Yes"]
    groups = next(a for a in report.areas if a.key == "groups")
    assert "Used by" in groups.columns
    billing = next(r for r in groups.rows if r[0] == "Billing")
    assert billing[groups.columns.index("Used by")] == "3"
    views = next(a for a in report.areas if a.key == "views")
    assert views.rows[0][views.columns.index("Restricted to")] == "Billing"


def test_docx_is_a_valid_word_file() -> None:
    data = render_docx(_report())
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode()
    assert "Zendesk configuration: current state" in xml
    assert "Route shoe tickets" in xml
    assert "custom ticket fields are not used" in xml


def test_html_escapes_content_and_prints() -> None:
    page = render_html(_report())
    assert page.startswith("<!doctype html>")
    assert "Old &lt;script&gt;" in page
    assert "<script>" not in page
    assert "window.print()" in page


def test_filename_includes_subdomain_and_date() -> None:
    assert report_filename(_report(), "docx") == "zendesk-current-state-acme-20261103.docx"


def test_word_report_survives_control_characters() -> None:
    areas = sample_instance()
    areas["macros"][0]["title"] = "Pasted\x0b from\x08 Word\x1f"
    areas["custom-roles"] = [{"id": 1, "name": "Lead", "description": "Line\x0cbreak"}]
    data = render_docx(build_report(make_snapshot(areas)))
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert "Pasted from Word" in xml


def test_support_addresses_lead_with_email_and_blank_missing_brand() -> None:
    areas = sample_instance()
    areas["support-addresses"].append({"id": 971, "email": "noreply@acme.test"})
    table = next(
        a for a in build_report(make_snapshot(areas)).areas if a.key == "support-addresses"
    )
    assert table.columns[:3] == ["Email", "Display name", "Brand"]
    assert table.rows[0][2] == "Main brand"
    assert table.rows[1][2] == ""


def test_incomplete_reads_say_unused_cannot_be_checked() -> None:
    areas = sample_instance()
    del areas["views"]
    report = build_report(make_snapshot(areas, unavailable=("views",)))
    titles = [f.title for f in report.findings]
    assert "Unused items could not be checked" in titles
    assert not any("not used" in t for t in titles)
