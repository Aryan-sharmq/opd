"""
Vision Radar - exports and reports
CSV (events, alerts) and a PDF report (summary counts, event table, evidence
images). Pure functions over already-fetched data: no database, no HTTP, so
the service decides WHAT is included and this module only formats it.

Times are written as UTC ISO-8601 plus the raw epoch value, because the server
does not know the reader's time zone.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

MAX_TABLE_ROWS = 300      # PDF event-table cap (CSV has no cap beyond the query limit)
MAX_IMAGES = 12           # PDF evidence-image cap, keeps the file small


def iso(ts: Optional[float]) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _safe(value) -> str:
    """Neutralise spreadsheet formula injection (=, +, -, @ at the start of a cell)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _csv(header: Sequence[str], rows: Iterable[Sequence]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([_safe(c) for c in r])
    return buf.getvalue()


def events_to_csv(events: Sequence[dict], zone_names: Dict[str, str]) -> str:
    return _csv(
        ["event_id", "event_type", "entity_type", "entity_ids", "zone", "state", "confidence",
         "start_time_utc", "end_time_utc", "duration_seconds", "start_epoch"],
        [[e["event_id"], e["event_type"], e["entity_type"], " ".join(e["entity_ids"]),
          zone_names.get(e["zone_id"], e["zone_id"] or ""), e["state"],
          "" if e["confidence"] is None else round(e["confidence"], 3),
          iso(e["start_time"]), iso(e["end_time"]),
          "" if e["duration_seconds"] is None else round(e["duration_seconds"], 2), e["start_time"]]
         for e in events])


def alerts_to_csv(alerts: Sequence[dict], zone_names: Dict[str, str]) -> str:
    return _csv(
        ["alert_id", "created_utc", "rule", "event_type", "zone", "confidence", "message", "event_id"],
        [[a["alert_id"], iso(a["created_at"]), a["rule_name"], a["event_type"],
          zone_names.get(a["zone_id"], a["zone_id"] or ""),
          "" if a["confidence"] is None else round(a["confidence"], 3), a["message"], a["event_id"]]
         for a in alerts])


def build_report_pdf(title: str, start: Optional[float], end: Optional[float],
                     events: Sequence[dict], alerts: Sequence[dict], zone_names: Dict[str, str],
                     images: Sequence[Tuple[dict, str]]) -> bytes:
    """images: (event dict, path to a JPEG already verified to be inside the evidence dir)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=8, leading=10)
    story: list = [Paragraph(_esc(title), styles["Title"])]
    period = (f"{iso(start)} to {iso(end)}" if start is not None and end is not None else "All recorded data")
    story += [Paragraph(f"Period: {_esc(period)}", styles["Normal"]),
              Paragraph(f"Generated: {iso(datetime.now(tz=timezone.utc).timestamp())}", styles["Normal"]),
              Spacer(1, 6 * mm)]

    def grid(data, widths=None):
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f5f9")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    story += [Paragraph("Summary", styles["Heading2"]),
              grid([["Total events", len(events)], ["Total alerts", len(alerts)]], [60 * mm, 40 * mm]),
              Spacer(1, 4 * mm)]
    for heading, counter in (("Events by type", Counter(e["event_type"] for e in events)),
                             ("Events by entity", Counter(e["entity_type"] or "unknown" for e in events)),
                             ("Events by zone", Counter(zone_names.get(e["zone_id"], e["zone_id"] or "no zone")
                                                        for e in events))):
        if counter:
            story += [Paragraph(heading, styles["Heading3"]),
                      grid([["Name", "Count"]] + [[_esc(k), v] for k, v in counter.most_common()],
                           [90 * mm, 30 * mm]), Spacer(1, 3 * mm)]

    if events:
        story.append(Paragraph("Events", styles["Heading2"]))
        rows = [["Time (UTC)", "Type", "Entity", "Zone", "Conf.", "State"]]
        for e in events[:MAX_TABLE_ROWS]:
            rows.append([Paragraph(iso(e["start_time"]), small), Paragraph(_esc(e["event_type"]), small),
                         Paragraph(_esc(e["entity_type"] or ""), small),
                         Paragraph(_esc(zone_names.get(e["zone_id"], e["zone_id"] or "")), small),
                         "" if e["confidence"] is None else f'{e["confidence"]:.2f}', _esc(e["state"])])
        story.append(grid(rows, [38 * mm, 36 * mm, 24 * mm, 36 * mm, 14 * mm, 22 * mm]))
        if len(events) > MAX_TABLE_ROWS:
            story.append(Paragraph(f"Showing the first {MAX_TABLE_ROWS} of {len(events)} events. "
                                   "Use the CSV export for the full list.", small))

    if alerts:
        story += [Spacer(1, 4 * mm), Paragraph("Alerts", styles["Heading2"])]
        rows = [["Time (UTC)", "Rule", "Message"]]
        for a in alerts[:MAX_TABLE_ROWS]:
            rows.append([Paragraph(iso(a["created_at"]), small), Paragraph(_esc(a["rule_name"] or ""), small),
                         Paragraph(_esc(a["message"] or ""), small)])
        story.append(grid(rows, [38 * mm, 40 * mm, 92 * mm]))

    if images:
        story += [Spacer(1, 4 * mm), Paragraph("Evidence images", styles["Heading2"])]
        for ev, path in images[:MAX_IMAGES]:
            try:
                img = Image(path)
                scale = min(120 * mm / img.imageWidth, 80 * mm / img.imageHeight, 1.0)
                img.drawWidth, img.drawHeight = img.imageWidth * scale, img.imageHeight * scale
            except Exception:                                     # noqa: BLE001 - unreadable image: skip it
                continue
            story += [Paragraph(f"{_esc(ev['event_type'])} &middot; {iso(ev['start_time'])} &middot; "
                                f"{_esc(ev['event_id'][:8])}", small), img, Spacer(1, 4 * mm)]

    out = io.BytesIO()
    SimpleDocTemplate(out, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                      bottomMargin=15 * mm, title=title).build(story)
    return out.getvalue()


def _esc(text) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
