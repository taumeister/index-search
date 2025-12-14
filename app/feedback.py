import logging
import smtplib
import time
import threading
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Iterable, Tuple

from bs4 import BeautifulSoup

from app.config_loader import CentralConfig

logger = logging.getLogger(__name__)

ALLOWED_TAGS = {"p", "div", "br", "strong", "b", "em", "i", "ul", "ol", "li", "span"}
MAX_FEEDBACK_CHARS = 5000
RATE_LIMIT_WINDOW_SECONDS = 300
RATE_LIMIT_MAX_REQUESTS = 5
_feedback_rate: dict[str, list[float]] = {}
_rate_lock = threading.Lock()


def sanitize_feedback_html(html: str) -> str:
    """
    Removes unsafe tags/attributes, keeps minimal formatting.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    for bad in soup(["script", "style"]):
        bad.decompose()
    for tag in soup.find_all(True):
        name = tag.name.lower()
        if name not in ALLOWED_TAGS:
            tag.unwrap()
            continue
        tag.attrs = {}
    if soup.body:
        cleaned = "".join(str(child) for child in soup.body.contents)
    else:
        cleaned = "".join(str(child) for child in soup.contents)
    return cleaned


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    return soup.get_text("\n")


def enforce_length(text: str) -> None:
    if len(text or "") > MAX_FEEDBACK_CHARS:
        raise ValueError(f"Feedback zu lang (max. {MAX_FEEDBACK_CHARS} Zeichen)")


def check_rate_limit(key: str) -> bool:
    now = time.time()
    with _rate_lock:
        recent = [ts for ts in _feedback_rate.get(key, []) if now - ts < RATE_LIMIT_WINDOW_SECONDS]
        if len(recent) >= RATE_LIMIT_MAX_REQUESTS:
            _feedback_rate[key] = recent
            return False
        recent.append(now)
        _feedback_rate[key] = recent
    return True


def build_bodies(message_html: str, message_text: str) -> Tuple[str, str]:
    html = sanitize_feedback_html(message_html or "")
    plain = (message_text or "").strip() or html_to_text(html).strip()
    if not plain:
        raise ValueError("Feedback-Text fehlt")
    enforce_length(plain)
    if not html.strip():
        html = "<p></p>"
    return html, plain


def render_email_payload(message_html: str, message_text: str, version: str) -> Tuple[str, str]:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    html_body, plain_text = build_bodies(message_html, message_text)
    version_line = f"{version} • {timestamp}"
    html = f"""
    <div style="font-family:'Segoe UI',Tahoma,sans-serif;background:#f5f7fb;padding:20px;">
      <div style="max-width:640px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:14px;box-shadow:0 12px 36px rgba(17,34,68,0.12);overflow:hidden;">
        <div style="padding:16px 18px 10px 18px;border-bottom:1px solid #e2e8f0;background:linear-gradient(120deg,#1b3a5d,#0f253d);color:#e8edf5;display:flex;justify-content:space-between;align-items:center;gap:10px;">
          <div style="font-weight:700;font-size:16px;">Feedback zur Dokumenten-Volltext-Suche</div>
          <div style="font-size:12px;color:#c4d1e1;">{version_line}</div>
        </div>
        <div style="padding:18px 20px;background:linear-gradient(180deg,#ffffff,#f7f9fb);">
          <div style="border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;background:#ffffff;line-height:1.6;font-size:13px;color:#0f172a;">
            {html_body}
          </div>
        </div>
      </div>
    </div>
    """
    text = f"""Feedback zur Dokumenten-Volltext-Suche
Version: {version}
Zeitpunkt: {timestamp}

{plain_text}
"""
    return html, text


def send_feedback_email(
    config: CentralConfig, recipients: Iterable[str], message_html: str, message_text: str, version: str
) -> None:
    if not recipients:
        raise ValueError("Kein Empfänger für Feedback konfiguriert")
    if not config.smtp:
        raise ValueError("SMTP nicht konfiguriert")

    html_body, text_body = render_email_payload(message_html, message_text, version)
    msg = EmailMessage()
    msg["Subject"] = f"Feedback zur Dokumenten-Volltext-Suche ({version})"
    msg["From"] = config.smtp.sender
    msg["To"] = ", ".join([r for r in recipients])
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(config.smtp.host, config.smtp.port, timeout=10) as server:
            if config.smtp.use_tls:
                server.starttls()
            if config.smtp.username:
                server.login(config.smtp.username, config.smtp.password or "")
            server.send_message(msg)
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("Feedback-Mail konnte nicht gesendet werden: %s", exc)
        raise
