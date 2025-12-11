import os
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from pypdf import PdfReader
from striprtf.striprtf import rtf_to_text

try:
    import extract_msg
except ImportError:  # pragma: no cover
    extract_msg = None


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


def extract_msg(path: Path) -> dict:
    if extract_msg is None:
        raise RuntimeError("extract-msg ist nicht installiert")
    msg = extract_msg.Message(str(path))
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


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n")
