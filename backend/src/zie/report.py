"""Current-state report: what the instance has today, for the customer.

One report model, two renderers: Word (.docx, via python-docx) and a self-contained HTML page
that prints cleanly (the browser's "Save as PDF" gives the PDF).
"""

from __future__ import annotations

import html
import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from zie import __version__
from zie.dependencies import TARGET_AREAS, DependencyGraph, unused_custom_ticket_fields
from zie.readers.areas import AREAS, AreaSpec, item_active, item_id, item_name
from zie.snapshot import Snapshot

MAX_CELL = 160
MAX_FINDINGS = 200
# Characters Word's XML cannot hold (Zendesk text pasted from other tools can contain them).
_XML_INVALID = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def xml_safe(text: str) -> str:
    return _XML_INVALID.sub("", text)


class SummaryRow(BaseModel):
    section: str
    area: str
    status: str
    items: int
    active: int | None
    inactive: int | None


class Finding(BaseModel):
    title: str
    detail: str
    items: list[str]


class AreaTable(BaseModel):
    key: str
    label: str
    section: str
    status: str
    message: str | None
    columns: list[str]
    rows: list[list[str]]


class Report(BaseModel):
    title: str
    subdomain: str
    taken_at: datetime
    engine_version: str
    summary: list[SummaryRow]
    findings: list[Finding]
    areas: list[AreaTable]


@dataclass
class _Ctx:
    graph: DependencyGraph
    names: dict[str, dict[str, str]]

    def name(self, area: str, target_id: Any) -> str:
        if target_id in (None, ""):
            return ""
        key = str(target_id)
        return self.names.get(area, {}).get(key, key)


Column = tuple[str, Callable[[dict[str, Any], _Ctx], str]]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value)
    return text if len(text) <= MAX_CELL else text[: MAX_CELL - 1] + "…"


def _get(field: str) -> Callable[[dict[str, Any], _Ctx], str]:
    return lambda item, _ctx: _text(item.get(field))


def _count(field: str) -> Callable[[dict[str, Any], _Ctx], str]:
    def get(item: dict[str, Any], _ctx: _Ctx) -> str:
        value = item.get(field)
        return str(len(value)) if isinstance(value, list) else ""

    return get


def _conditions(field: str) -> Callable[[dict[str, Any], _Ctx], str]:
    def get(item: dict[str, Any], _ctx: _Ctx) -> str:
        block = item.get(field)
        if isinstance(block, dict):
            return str(len(block.get("all") or []) + len(block.get("any") or []))
        return str(len(block)) if isinstance(block, list) else ""

    return get


def _restricted(item: dict[str, Any], ctx: _Ctx) -> str:
    restriction = item.get("restriction")
    if not isinstance(restriction, dict):
        return "Everyone"
    if restriction.get("type") == "Group":
        ids = restriction.get("ids") or [restriction.get("id")]
        return _text(", ".join(ctx.name("groups", i) for i in ids if i is not None))
    return "One agent"


def _used_by(area: str) -> Column:
    return ("Used by", lambda item, ctx: str(ctx.graph.used_by_count(area, item_id(item))))


def _settings_count(item: dict[str, Any], _ctx: _Ctx) -> str:
    return str(len([k for k in item if k not in ("id", "name")]))


EXTRA_COLUMNS: dict[str, list[Column]] = {
    "account-settings": [("Settings", _settings_count)],
    "brands": [("Subdomain", _get("subdomain")), ("Default", _get("default"))],
    "support-addresses": [
        ("Display name", _get("name")),
        ("Brand", lambda item, ctx: ctx.name("brands", item.get("brand_id"))),
        ("Default", _get("default")),
    ],
    "groups": [("Default", _get("default")), ("Public", _get("is_public"))],
    "custom-roles": [("Description", _get("description"))],
    "user-fields": [("Key", _get("key")), ("Type", _get("type"))],
    "organization-fields": [("Key", _get("key")), ("Type", _get("type"))],
    "ticket-fields": [
        ("Type", _get("type")),
        ("Required", _get("required")),
        ("Options", _count("custom_field_options")),
    ],
    "ticket-forms": [("Fields", _count("ticket_field_ids")), ("Default", _get("default"))],
    "custom-statuses": [("Category", _get("status_category"))],
    "views": [("Restricted to", _restricted), ("Conditions", _conditions("conditions"))],
    "macros": [("Restricted to", _restricted), ("Actions", _count("actions"))],
    "triggers": [
        (
            "Category",
            lambda item, ctx: (
                ctx.name("trigger-categories", item.get("category_id"))
                if item.get("category_id")
                else ""
            ),
        ),
        ("Conditions", _conditions("conditions")),
        ("Actions", _count("actions")),
    ],
    "trigger-categories": [("Position", _get("position"))],
    "automations": [("Conditions", _conditions("conditions")), ("Actions", _count("actions"))],
    "sla-policies": [("Conditions", _conditions("filter")), ("Targets", _count("policy_metrics"))],
    "schedules": [("Time zone", _get("time_zone"))],
    "dynamic-content": [("Placeholder", _get("placeholder")), ("Variants", _count("variants"))],
    "webhooks": [("Endpoint", _get("endpoint")), ("Method", _get("http_method"))],
    "apps": [("App ID", _get("app_id"))],
    "custom-objects": [("Key", _get("key"))],
}


def _columns(spec: AreaSpec) -> list[Column]:
    first = {"account-settings": "Section", "support-addresses": "Email"}.get(spec.key, "Name")
    columns: list[Column] = [(first, lambda item, _ctx: _text(item_name(spec, item)))]
    columns += EXTRA_COLUMNS.get(spec.key, [])
    if spec.active_field:
        columns.append(
            (
                "Active",
                lambda item, _ctx: {True: "Yes", False: "No", None: ""}[item_active(spec, item)],
            )
        )
    if spec.key in TARGET_AREAS:
        columns.append(_used_by(spec.key))
    if spec.key != "account-settings":
        columns.append(("Updated", lambda item, _ctx: _text(item.get("updated_at"))[:10]))
        columns.append(("ID", lambda item, _ctx: item_id(item)))
    return columns


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def build_report(snapshot: Snapshot, graph: DependencyGraph | None = None) -> Report:
    graph = graph or DependencyGraph.build(snapshot)
    names: dict[str, dict[str, str]] = {}
    for spec in AREAS:
        result = snapshot.area(spec.key)
        names[spec.key] = {item_id(i): item_name(spec, i) for i in (result.items if result else [])}
    ctx = _Ctx(graph=graph, names=names)

    summary: list[SummaryRow] = []
    tables: list[AreaTable] = []
    for spec in AREAS:
        result = snapshot.area(spec.key)
        if result is None:
            continue
        flags = [item_active(spec, i) for i in result.items]
        known = [f for f in flags if f is not None]
        summary.append(
            SummaryRow(
                section=spec.section,
                area=spec.label,
                status={"ok": "Read", "unavailable": "Not available", "error": "Error"}[
                    result.status
                ],
                items=result.count,
                active=sum(1 for f in known if f) if known else None,
                inactive=sum(1 for f in known if not f) if known else None,
            )
        )
        columns = _columns(spec)
        tables.append(
            AreaTable(
                key=spec.key,
                label=spec.label,
                section=spec.section,
                status=result.status,
                message=result.message,
                columns=[c[0] for c in columns],
                rows=[[get(item, ctx) for _, get in columns] for item in result.items],
            )
        )

    findings: list[Finding] = []
    unused = unused_custom_ticket_fields(snapshot, graph)
    if unused:
        findings.append(
            Finding(
                title=_plural(len(unused), "custom ticket field is", "custom ticket fields are")
                + " not used",
                detail="No trigger, automation, macro, view, SLA policy or ticket form refers "
                "to them. Candidates to retire after checking reports and integrations.",
                items=[f.name for f in unused[:MAX_FINDINGS]],
            )
        )
    broken = graph.broken()
    if broken:
        findings.append(
            Finding(
                title=_plural(
                    len(broken),
                    "reference points at an item that no longer exists",
                    "references point at items that no longer exist",
                ),
                detail="These rules refer to an ID the instance does not have. They may "
                "silently do nothing.",
                items=[
                    f"{r.source.label}: {r.source.name} → {r.target.label} {r.target.id} "
                    f"({r.context})"
                    for r in broken[:MAX_FINDINGS]
                ],
            )
        )
    if not graph.complete:
        findings.append(
            Finding(
                title="Unused items could not be checked",
                detail="These areas were not read, so references from them are unknown: "
                + ", ".join(graph.incomplete_areas)
                + ".",
                items=[],
            )
        )
    inactive = [
        f"{row.area}: {row.inactive} of {row.items}"
        for row in summary
        if row.area in ("Triggers", "Automations", "Macros", "Views") and row.inactive
    ]
    if inactive:
        findings.append(
            Finding(
                title="Inactive business rules",
                detail="Inactive rules do nothing but add clutter; review before go-live.",
                items=inactive,
            )
        )

    return Report(
        title="Zendesk configuration: current state",
        subdomain=snapshot.subdomain,
        taken_at=snapshot.taken_at,
        engine_version=__version__,
        summary=summary,
        findings=findings,
        areas=tables,
    )


def report_filename(report: Report, extension: str) -> str:
    return f"zendesk-current-state-{report.subdomain}-{report.taken_at:%Y%m%d}.{extension}"


def _subtitle(report: Report) -> str:
    return (
        f"{report.subdomain}.zendesk.com · read {report.taken_at:%d %b %Y, %H:%M} UTC · "
        f"Zendesk Implementation Engine {report.engine_version}"
    )


def render_docx(report: Report) -> bytes:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    doc = Document()
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Cm(1.6))
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(10)

    def table(columns: list[str], rows: list[list[str]]) -> None:
        grid = doc.add_table(rows=1, cols=len(columns))
        grid.style = "Light Grid Accent 1"
        for cell, title in zip(grid.rows[0].cells, columns, strict=True):
            cell.text = xml_safe(title)
        # Repeat the header row at the top of every page the table runs onto.
        header = grid.rows[0]._tr.get_or_add_trPr()
        repeat = OxmlElement("w:tblHeader")
        repeat.set(qn("w:val"), "true")
        header.append(repeat)
        for row in rows:
            cells = grid.add_row().cells
            for cell, value in zip(cells, row, strict=True):
                cell.text = xml_safe(value)
        for row_cells in grid.rows:
            for cell in row_cells.cells:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(8.5)

    def heading(text: str, level: int) -> None:
        doc.add_heading(xml_safe(text), level)

    def paragraph(text: str, style: str | None = None) -> Any:
        return doc.add_paragraph(xml_safe(text), style=style)

    heading(report.title, 0)
    paragraph(_subtitle(report))

    heading("Summary", 1)
    table(
        ["Section", "Area", "Status", "Items", "Active", "Inactive"],
        [
            [
                r.section,
                r.area,
                r.status,
                str(r.items),
                "" if r.active is None else str(r.active),
                "" if r.inactive is None else str(r.inactive),
            ]
            for r in report.summary
        ],
    )

    heading("Findings", 1)
    if not report.findings:
        paragraph("No findings.")
    for finding in report.findings:
        heading(finding.title, 2)
        paragraph(finding.detail)
        for line in finding.items:
            paragraph(line, style="List Bullet")

    current_section = None
    for area in report.areas:
        if area.section != current_section:
            current_section = area.section
            heading(area.section, 1)
        heading(f"{area.label} ({len(area.rows)})", 2)
        if area.status != "ok":
            paragraph(area.message or "Not read.").runs[0].italic = True
        elif not area.rows:
            paragraph("None configured.")
        else:
            table(area.columns, area.rows)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


_CSS = """
body { font: 13px/1.45 'Segoe UI', system-ui, sans-serif; color: #1f2328;
  margin: 32px auto; max-width: 1200px; padding: 0 16px; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 19px; margin: 32px 0 8px; border-bottom: 1px solid #d0d7de;
  padding-bottom: 4px; }
h3 { font-size: 15px; margin: 20px 0 6px; }
.sub { color: #59636e; margin: 0 0 20px; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 12px; font-size: 12px; }
th, td { border: 1px solid #d0d7de; padding: 4px 6px; text-align: left; vertical-align: top; }
th { background: #f3f5f7; }
tr:nth-child(even) td { background: #fafbfc; }
.note { color: #59636e; font-style: italic; }
.toolbar { position: sticky; top: 0; background: #fff; padding: 8px 0; margin-bottom: 8px; }
button { font: inherit; padding: 6px 14px; border-radius: 6px; border: 1px solid #0e7c66;
  background: #0e7c66; color: #fff; cursor: pointer; }
@media print {
  .toolbar { display: none; }
  body { margin: 0; max-width: none; }
  h2, h3 { break-after: avoid; }
  tr { break-inside: avoid; }
}
"""


def render_html(report: Report) -> str:
    e = html.escape

    def table(columns: list[str], rows: list[list[str]]) -> str:
        head = "".join(f"<th>{e(c)}</th>" for c in columns)
        body = "".join("<tr>" + "".join(f"<td>{e(v)}</td>" for v in row) + "</tr>" for row in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{e(report.title)} - {e(report.subdomain)}</title><style>{_CSS}</style></head>",
        "<body><div class='toolbar'><button onclick='window.print()'>"
        "Print or save as PDF</button></div>",
        f"<h1>{e(report.title)}</h1><p class='sub'>{e(_subtitle(report))}</p>",
        "<h2>Summary</h2>",
        table(
            ["Section", "Area", "Status", "Items", "Active", "Inactive"],
            [
                [
                    r.section,
                    r.area,
                    r.status,
                    str(r.items),
                    "" if r.active is None else str(r.active),
                    "" if r.inactive is None else str(r.inactive),
                ]
                for r in report.summary
            ],
        ),
        "<h2>Findings</h2>",
    ]
    if not report.findings:
        parts.append("<p>No findings.</p>")
    for finding in report.findings:
        items = "".join(f"<li>{e(i)}</li>" for i in finding.items)
        parts.append(f"<h3>{e(finding.title)}</h3><p>{e(finding.detail)}</p><ul>{items}</ul>")
    current_section = None
    for area in report.areas:
        if area.section != current_section:
            current_section = area.section
            parts.append(f"<h2>{e(area.section)}</h2>")
        parts.append(f"<h3>{e(area.label)} ({len(area.rows)})</h3>")
        if area.status != "ok":
            parts.append(f"<p class='note'>{e(area.message or 'Not read.')}</p>")
        elif not area.rows:
            parts.append("<p class='note'>None configured.</p>")
        else:
            parts.append(table(area.columns, area.rows))
    parts.append("</body></html>")
    return "".join(parts)
