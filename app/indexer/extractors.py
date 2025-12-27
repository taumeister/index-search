import os
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from pypdf import PdfReader
from striprtf.striprtf import rtf_to_text
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

try:
    import extract_msg as extract_msg_lib
except ImportError:  # pragma: no cover
    extract_msg_lib = None


def read_text_file(path: Path, max_bytes: Optional[int] = None) -> str:
    with open(path, "r", errors="ignore") as f:
        if max_bytes:
            return f.read(max_bytes)
        return f.read()


def extract_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    texts = []
    for page in reader.pages:
        texts.append(page.extract_text() or "")
    return "\n".join(texts)


def extract_rtf(path: Path) -> str:
    raw = read_text_file(path)
    return rtf_to_text(raw)


def extract_msg_file(path: Path) -> dict:
    if extract_msg_lib is None:
        raise RuntimeError("extract-msg ist nicht installiert")
    msg = extract_msg_lib.Message(str(path))
    msg_subject = msg.subject or ""
    msg_from = msg.sender or ""
    msg_to = ", ".join(msg.to or [])
    msg_cc = ", ".join(msg.cc or []) if msg.cc else ""
    msg_date = ""
    if msg.date:
        try:
            msg_date = date_parser.parse(msg.date).isoformat()
        except Exception:
            msg_date = str(msg.date)
    body = msg.body or msg.htmlBody or ""
    if msg.htmlBody:
        body = clean_html(msg.htmlBody)
    return {
        "content": body,
        "title_or_subject": msg_subject,
        "msg_from": msg_from,
        "msg_to": msg_to,
        "msg_cc": msg_cc,
        "msg_subject": msg_subject,
        "msg_date": msg_date,
    }


def _to_str(val) -> str:
    if isinstance(val, bytes):
        try:
            return val.decode("utf-8", errors="ignore")
        except Exception:
            return str(val)
    return str(val) if val is not None else ""


def _ensure_text(value, charset: Optional[str] = None) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode(charset or "utf-8", errors="ignore")
        except Exception:
            return value.decode("utf-8", errors="ignore")
    return _to_str(value)


def extract_mail_file(path: Path) -> dict:
    with path.open("rb") as f:
        raw = f.read()
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    subject = msg.get("Subject", "") or ""
    sender = msg.get("From", "") or ""
    to = msg.get("To", "") or ""
    cc = msg.get("Cc", "") or ""
    msg_id = msg.get("Message-ID", "") or msg.get("Message-Id", "") or ""
    date_val = ""
    try:
        parsed = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else None
        if parsed:
            date_val = parsed.isoformat()
    except Exception:
        date_val = msg.get("Date", "") or ""

    attachments: list[str] = []
    body_text = ""
    html_text = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            filename = part.get_filename()
            if filename:
                attachments.append(_to_str(filename))
            content_type = part.get_content_type()
            try:
                payload = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    try:
                        payload = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                    except Exception:
                        payload = ""
            text_payload = _ensure_text(payload, part.get_content_charset())
            if content_type == "text/plain" and not body_text:
                body_text = text_payload
            elif content_type == "text/html" and not body_text:
                html_text = text_payload
    else:
        try:
            body_text = msg.get_content()
        except Exception:
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes):
                try:
                    body_text = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
                except Exception:
                    body_text = ""
            else:
                body_text = _ensure_text(payload, msg.get_content_charset())

    if not body_text and html_text:
        body_text = clean_html(html_text)
    elif html_text:
        # prefer plain but keep HTML fallback if plain is empty/whitespace
        body_text = body_text or clean_html(html_text)

    index_parts = [subject, sender, to, cc, body_text or ""]
    index_content = "\n".join([_ensure_text(part) for part in index_parts]).strip()

    attachments_str = ", ".join([att for att in attachments if att])
    return {
        "content": index_content,
        "title_or_subject": subject or path.name,
        "msg_from": sender,
        "msg_to": to,
        "msg_cc": cc,
        "msg_subject": subject,
        "msg_date": date_val,
        "msg_message_id": msg_id,
        "msg_attachments": attachments_str,
        "body": body_text or "",
    }


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n")
