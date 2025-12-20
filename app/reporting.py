import html
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple

from app import config_db
from app.config_loader import CentralConfig
from app.db import datenbank as db

logger = logging.getLogger(__name__)

DEFAULT_THEME = "lumen-atelier"
INLINE_LIMIT = 50


THEME_TOKENS: Dict[str, Dict[str, str]] = {
    "lumen-atelier": {
        "bg": "#f6f4ef",
        "surface": "#ffffff",
        "surface_muted": "#f0eee8",
        "surface_strong": "#e8e2d6",
        "text": "#2c333a",
        "text_strong": "#191f25",
        "muted": "#6e727b",
        "inverse": "#f8fafc",
        "accent": "#3f8f75",
        "accent_soft": "#65b49b",
        "accent_strong": "#2f6f5b",
        "accent_contrast": "#255646",
        "success": "#2f9a5d",
        "warning": "#c6832b",
        "danger": "#b54747",
        "info": "#2f6fa6",
        "border": "#d8d1c4",
        "border_strong": "#c9c1b2",
        "highlight_bg": "#f7e7c6",
        "highlight_fg": "#5b3f15",
    },
    "marble-coast": {
        "bg": "#eef3f5",
        "surface": "#ffffff",
        "surface_muted": "#e6eff3",
        "surface_strong": "#dce7ed",
        "text": "#22313a",
        "text_strong": "#142029",
        "muted": "#63707d",
        "inverse": "#f8fafc",
        "accent": "#2f8fb8",
        "accent_soft": "#5bb3d8",
        "accent_strong": "#1f6e8f",
        "accent_contrast": "#1b5672",
        "success": "#2fa688",
        "warning": "#c48b2b",
        "danger": "#b54f54",
        "info": "#2f74b0",
        "border": "#cbd7df",
        "border_strong": "#b8c8d3",
        "highlight_bg": "#d8eef9",
        "highlight_fg": "#0f3c4f",
    },
    "aurora-atelier": {
        "bg": "#fdfaf5",
        "surface": "#ffffff",
        "surface_muted": "#f5efe5",
        "surface_strong": "#ede3d8",
        "text": "#2b2823",
        "text_strong": "#14110d",
        "muted": "#7a7770",
        "inverse": "#f9fbff",
        "accent": "#6fb8c9",
        "accent_soft": "#9cd7e5",
        "accent_strong": "#5599a8",
        "accent_contrast": "#3c7a89",
        "success": "#3a9f76",
        "warning": "#c78a2c",
        "danger": "#c9535c",
        "info": "#4b88d1",
        "border": "#ded6c9",
        "border_strong": "#cfc5b6",
        "highlight_bg": "#fbe6d2",
        "highlight_fg": "#5f3c14",
    },
    "nocturne-atlas": {
        "bg": "#0f1724",
        "surface": "#161f2c",
        "surface_muted": "#1d2736",
        "surface_strong": "#253143",
        "text": "#d0d9ea",
        "text_strong": "#e3ecfb",
        "muted": "#8fa2bd",
        "inverse": "#f5f8ff",
        "accent": "#48c1c8",
        "accent_soft": "#74d9de",
        "accent_strong": "#2f8ca0",
        "accent_contrast": "#1e6171",
        "success": "#4ad1a6",
        "warning": "#e5b567",
        "danger": "#e66f7b",
        "info": "#6fb0ff",
        "border": "#2d3a4a",
        "border_strong": "#3a4a61",
        "highlight_bg": "#233449",
        "highlight_fg": "#cdeafe",
    },
    "graphite-ember": {
        "bg": "#121519",
        "surface": "#1c1f27",
        "surface_muted": "#222734",
        "surface_strong": "#2a303c",
        "text": "#d9dfe8",
        "text_strong": "#f5f7fb",
        "muted": "#a6acb9",
        "inverse": "#f7f7fa",
        "accent": "#e07a5f",
        "accent_soft": "#f4a37f",
        "accent_strong": "#c35e46",
        "accent_contrast": "#9f412d",
        "success": "#52c49a",
        "warning": "#e9b44c",
        "danger": "#f05f67",
        "info": "#8fb3ff",
        "border": "#2f343f",
        "border_strong": "#3b424f",
        "highlight_bg": "#332620",
        "highlight_fg": "#ffd9c7",
    },
    "velvet-eclipse": {
        "bg": "#0f0c17",
        "surface": "#181425",
        "surface_muted": "#201c2f",
        "surface_strong": "#29233a",
        "text": "#e5e2f2",
        "text_strong": "#f7f4ff",
        "muted": "#b1adc8",
        "inverse": "#f8f7ff",
        "accent": "#b47de6",
        "accent_soft": "#d2b0ff",
        "accent_strong": "#8d5dc5",
        "accent_contrast": "#6b3aa8",
        "success": "#71d7b5",
        "warning": "#f3c77c",
        "danger": "#f17c9a",
        "info": "#87b5ff",
        "border": "#2f2940",
        "border_strong": "#3a324e",
        "highlight_bg": "#33244a",
        "highlight_fg": "#f7ecff",
    },
    "obsidian-prism": {
        "bg": "#06070a",
        "surface": "#0d1016",
        "surface_muted": "#121623",
        "surface_strong": "#181d2c",
        "text": "#dde3f3",
        "text_strong": "#f2f6ff",
        "muted": "#9aa4c0",
        "inverse": "#050608",
        "accent": "#5ae2ff",
        "accent_soft": "#8cf0ff",
        "accent_strong": "#38b7d3",
        "accent_contrast": "#1d7c99",
        "success": "#67f5c2",
        "warning": "#f4c06a",
        "danger": "#ff6f9f",
        "info": "#8ab0ff",
        "border": "#20283a",
        "border_strong": "#2c3550",
        "highlight_bg": "#1c2335",
        "highlight_fg": "#d9e8ff",
    },
}


def resolve_theme(theme_id: Optional[str]) -> Tuple[str, Dict[str, str]]:
    theme = (theme_id or "").strip().lower() or DEFAULT_THEME
    if theme not in THEME_TOKENS:
        theme = DEFAULT_THEME
    return theme, THEME_TOKENS[theme]


def _fmt_ts(value: Optional[str]) -> str:
    if not value:
        return "–"
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return value


def _fmt_duration(start: Optional[str], end: Optional[str]) -> str:
    if not start or not end:
        return "–"
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        return f"{max(0, int(end_dt.timestamp() - start_dt.timestamp()))}s"
    except Exception:
        return "–"


def load_run_report_data(run_id: int) -> Dict[str, Any]:
    with db.get_conn() as conn:
        run = conn.execute("SELECT * FROM index_runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            raise ValueError(f"Run {run_id} nicht gefunden")
        action_counts: Dict[str, int] = {}
        for row in conn.execute(
            "SELECT action, COUNT(*) as c FROM index_run_events WHERE run_id = ? GROUP BY action", (run_id,)
        ):
            action_counts[row["action"]] = row["c"]
        events: Dict[str, List[Dict[str, Any]]] = {"added": [], "updated": [], "removed": []}
        for row in db.list_all_index_events(conn, run_id):
            events.setdefault(row["action"], []).append(dict(row))
        errors = [dict(r) for r in db.list_all_run_errors(conn, run_id, include_ignored=False)]
    return {
        "run": dict(run),
        "actions": action_counts,
        "events": events,
        "errors": errors,
    }


def _render_badge(label: str, value: Any, color: str, text_color: str) -> str:
    return (
        f'<div style="padding:10px 12px;border-radius:12px;'
        f'background:{color};color:{text_color};font-weight:700;'
        f'display:flex;flex-direction:column;gap:4px;min-width:120px;'
        f'box-shadow:0 6px 18px rgba(0,0,0,0.08);">'
        f'<div style="font-size:12px;font-weight:600;opacity:0.9;">{label}</div>'
        f'<div style="font-size:22px;line-height:1;">{value}</div>'
        f"</div>"
    )


def _render_table(rows: List[Dict[str, Any]], theme: Dict[str, str], kind: str) -> str:
    header_cells = ["Pfad", "Quelle/Info", "Zeitpunkt"]
    if kind == "errors":
        header_cells = ["Pfad", "Fehler", "Zeitpunkt"]
    head = "".join(f'<th style="padding:8px;border-bottom:1px solid {theme["border"]};text-align:left;font-size:12px;color:{theme["muted"]};">{html.escape(col)}</th>' for col in header_cells)
    body_parts = []
    for row in rows:
        path = row.get("path") or ""
        source = row.get("source") or ""
        message = row.get("message") or row.get("error_type") or ""
        ts = row.get("ts") or row.get("created_at") or ""
        detail = message
        if kind == "errors":
            err_type = row.get("error_type") or ""
            detail = f"{err_type}: {row.get('message') or ''}".strip(": ")
        body_parts.append(
            "<tr>"
            f'<td style="padding:8px 10px;border-bottom:1px solid {theme["border"]};font-size:12px;color:{theme["text_strong"]};word-break:break-word;">{html.escape(path)}</td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid {theme["border"]};font-size:12px;color:{theme["muted"]};word-break:break-word;">{html.escape(source)}'
            + (f'<div style="margin-top:4px;color:{theme["text"]};">{html.escape(detail)}</div>' if detail else "")
            + "</td>"
            f'<td style="padding:8px 10px;border-bottom:1px solid {theme["border"]};font-size:12px;color:{theme["muted"]};white-space:nowrap;">{html.escape(_fmt_ts(ts))}</td>'
            "</tr>"
        )
    body = "".join(body_parts) or f'<tr><td colspan="3" style="padding:10px;font-size:12px;color:{theme["muted"]};">Keine Einträge.</td></tr>'
    return (
        f'<table style="width:100%;border-collapse:collapse;margin-top:6px;">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{body}</tbody>"
        f"</table>"
    )


def _render_section(title: str, rows: List[Dict[str, Any]], theme: Dict[str, str], limit: Optional[int], kind: str) -> str:
    total = len(rows)
    visible = rows if limit is None else rows[:limit]
    note = ""
    if limit is not None and total > limit:
        note = f'<div style="margin-top:6px;font-size:12px;color:{theme["muted"]};">Weitere {total - limit} Einträge im Anhang.</div>'
    summary_style = (
        f'display:flex;align-items:center;gap:10px;font-weight:700;color:{theme["text_strong"]};'
        f'font-size:14px;'
    )
    section_bg = theme.get("surface_muted", "#f5f5f5")
    return (
        f'<details open style="margin:0 0 12px 0;padding:10px 12px;border:1px solid {theme["border"]};'
        f'border-radius:10px;background:{section_bg};">'
        f'<summary style="{summary_style}">{html.escape(title)}'
        f'<span style="padding:4px 8px;border-radius:999px;border:1px solid {theme["border"]};'
        f'background:{theme.get("surface", "#fff")};font-size:12px;margin-left:6px;">{total}</span>'
        f"</summary>"
        f'<div style="margin-top:8px;">{_render_table(visible, theme, kind)}</div>'
        f"{note}"
        f"</details>"
    )


def _build_html(run_data: Dict[str, Any], theme: Dict[str, str], theme_name: str, inline_limit: Optional[int]) -> str:
    run = run_data.get("run", {})
    started_at = run.get("started_at")
    finished_at = run.get("finished_at")
    duration = _fmt_duration(started_at, finished_at)
    counts = {
        "added": run.get("added", 0),
        "updated": run.get("updated", 0),
        "removed": run.get("removed", 0),
        "errors": run.get("errors", 0),
    }
    errors = run_data.get("errors", [])
    sections = []
    events = run_data.get("events", {})
    sections.append(_render_section("Hinzugefügt", events.get("added", []), theme, inline_limit, "events"))
    sections.append(_render_section("Aktualisiert", events.get("updated", []), theme, inline_limit, "events"))
    sections.append(_render_section("Entfernt / Verwaist", events.get("removed", []), theme, inline_limit, "events"))
    if errors:
        sections.append(_render_section("Fehler", errors, theme, inline_limit, "errors"))

    badges = "".join(
        [
            _render_badge("Hinzugefügt", counts["added"], theme["accent_soft"], theme["text_strong"]),
            _render_badge("Aktualisiert", counts["updated"], theme["surface_strong"], theme["text_strong"]),
            _render_badge("Entfernt", counts["removed"], theme["surface_muted"], theme["text_strong"]),
            _render_badge("Fehler", counts["errors"], theme["highlight_bg"], theme["highlight_fg"]),
        ]
    )

    header_grad = f"linear-gradient(120deg,{theme['accent_strong']},{theme['accent_contrast']})"
    border = theme["border"]
    body = (
        f'<div style="font-family:\'Segoe UI\',Tahoma,sans-serif;background:{theme["bg"]};padding:20px;">'
        f'<div style="max-width:760px;margin:0 auto;background:{theme["surface"]};border:1px solid {border};'
        f'border-radius:14px;box-shadow:0 12px 32px rgba(17,34,68,0.12);overflow:hidden;">'
        f'<div style="padding:16px 18px;border-bottom:1px solid {border};background:{header_grad};'
        f'color:{theme["inverse"]};display:flex;justify-content:space-between;align-items:center;gap:10px;">'
        f'<div style="font-weight:700;font-size:16px;">Index-Report</div>'
        f'<div style="font-size:12px;opacity:0.9;">Run #{run.get("id","?")} • {html.escape(run.get("status",""))}</div>'
        f"</div>"
        f'<div style="padding:18px 20px;background:linear-gradient(180deg,{theme["surface"]},{theme["surface_muted"]});">'
        f'<div style="margin-bottom:12px;display:flex;flex-direction:column;gap:6px;color:{theme["text"]};font-size:13px;">'
        f'<div><strong>Start:</strong> {_fmt_ts(started_at)}</div>'
        f'<div><strong>Ende:</strong> {_fmt_ts(finished_at)}</div>'
        f'<div><strong>Dauer:</strong> {duration}</div>'
        f'<div><strong>Status:</strong> {html.escape(run.get("status",""))}</div>'
        f'<div><strong>Theme:</strong> {html.escape(theme_name)}</div>'
        f"</div>"
        f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:14px;">'
        f"{badges}"
        f"</div>"
        f'<div style="display:flex;flex-direction:column;gap:10px;">{"".join(sections)}</div>'
        f"</div>"
        f"</div>"
        f"</div>"
    )
    return (
        "<!DOCTYPE html>"
        "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Index-Report #{run.get('id','?')}</title></head><body>"
        f"{body}"
        "</body></html>"
    )


def _build_plaintext(run_data: Dict[str, Any]) -> str:
    run = run_data.get("run", {})
    lines = [
        f"Index-Report #{run.get('id','?')}",
        f"Status: {run.get('status','')}",
        f"Start: {_fmt_ts(run.get('started_at'))}",
        f"Ende: {_fmt_ts(run.get('finished_at'))}",
        f"Dauer: {_fmt_duration(run.get('started_at'), run.get('finished_at'))}",
        f"Hinzugefügt: {run.get('added',0)}",
        f"Aktualisiert: {run.get('updated',0)}",
        f"Entfernt/Verwaist: {run.get('removed',0)}",
        f"Fehler: {run.get('errors',0)}",
        "",
        "Details: Siehe HTML-Mail bzw. Anhang.",
    ]
    return "\n".join(lines)


def render_index_report(run_data: Dict[str, Any], theme_id: Optional[str] = None, inline_limit: int = INLINE_LIMIT) -> Tuple[str, str, str, str]:
    theme_name, tokens = resolve_theme(theme_id)
    inline_html = _build_html(run_data, tokens, theme_name, inline_limit)
    attachment_html = _build_html(run_data, tokens, theme_name, None)
    plain_text = _build_plaintext(run_data)
    return theme_name, inline_html, attachment_html, plain_text


def build_report_email(
    sender: str,
    recipients: List[str],
    subject: str,
    inline_html: str,
    plain_text: str,
    attachment_html: str,
    attachment_name: str,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join([str(r) for r in recipients])
    msg.set_content(plain_text)
    msg.add_alternative(inline_html, subtype="html")
    msg.add_attachment(
        attachment_html,
        subtype="html",
        filename=attachment_name,
    )
    return msg


def send_run_report_email(config: CentralConfig, run_id: int) -> None:
    smtp = config.smtp
    if not smtp:
        logger.info("Kein SMTP konfiguriert, überspringe Report")
        return
    if config_db.get_setting("send_report_enabled", "0") != "1":
        logger.info("Report Versand deaktiviert")
        return
    try:
        run_data = load_run_report_data(run_id)
    except Exception as exc:
        logger.error("Report-Daten konnten nicht geladen werden: %s", exc)
        return

    theme_preference = config_db.get_setting("theme", None)
    theme_name, inline_html, attachment_html, plain_text = render_index_report(run_data, theme_preference)

    started_at = run_data.get("run", {}).get("started_at")
    started_label = ""
    try:
        if started_at:
            started_label = datetime.fromisoformat(started_at).strftime("%Y-%m-%d")
    except Exception:
        started_label = ""
    subject = f"Index-Report: {run_data.get('run', {}).get('status', '')} – {started_label or datetime.now().strftime('%Y-%m-%d')}"
    attachment_name = f"index-report-{run_id}-{started_label or datetime.now().strftime('%Y%m%d')}.html"

    msg = build_report_email(
        sender=smtp.sender,
        recipients=[str(r) for r in smtp.recipients],
        subject=subject,
        inline_html=inline_html,
        plain_text=plain_text,
        attachment_html=attachment_html,
        attachment_name=attachment_name,
    )
    try:
        with smtplib.SMTP(smtp.host, smtp.port, timeout=10) as server:
            if smtp.use_tls:
                server.starttls()
            if smtp.username:
                server.login(smtp.username, smtp.password or "")
            server.send_message(msg)
        logger.info("Report gesendet an %s", smtp.recipients)
    except Exception as exc:  # pragma: no cover
        logger.error("Report-Versand fehlgeschlagen: %s", exc)
