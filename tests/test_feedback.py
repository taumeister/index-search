import os

from fastapi.testclient import TestClient

from app import config_db
from app.db import datenbank as db
from app.config_loader import load_config
from app.feedback import MAX_FEEDBACK_CHARS
from app import feedback
from app.main import create_app


def setup_env(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "feedback.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    os.environ["ADMIN_PASSWORD"] = "admin"
    for key in [
        "INDEX_ROOTS",
        "INDEX_WORKER_COUNT",
        "INDEX_MAX_FILE_SIZE_MB",
        "SEARCH_DEFAULT_MODE",
        "SEARCH_PREFIX_MINLEN",
        "FEEDBACK_ENABLED",
        "FEEDBACK_TO",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USE_TLS",
        "SMTP_USER",
        "SMTP_PASS",
        "SMTP_FROM",
        "SMTP_TO",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(feedback, "_feedback_rate", {})
    os.environ["APP_SECRET"] = "secret"


def test_feedback_disabled(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    os.environ["FEEDBACK_ENABLED"] = "false"
    os.environ["FEEDBACK_TO"] = "team@example.org"
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    resp = client.post("/api/feedback", json={"message_text": "hi"}, headers={"X-App-Secret": os.environ["APP_SECRET"]})
    assert resp.status_code == 403


def test_feedback_requires_smtp(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    os.environ["FEEDBACK_ENABLED"] = "true"
    os.environ["FEEDBACK_TO"] = "team@example.org"
    # kein SMTP_HOST => smtp None
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    resp = client.post("/api/feedback", json={"message_text": "hi"}, headers={"X-App-Secret": os.environ["APP_SECRET"]})
    assert resp.status_code == 503


def test_feedback_sends_mail(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    os.environ["FEEDBACK_ENABLED"] = "true"
    os.environ["FEEDBACK_TO"] = "team@example.org"
    os.environ["SMTP_HOST"] = "smtp.example.org"
    os.environ["SMTP_PORT"] = "587"
    os.environ["SMTP_USE_TLS"] = "true"
    os.environ["SMTP_USER"] = "user"
    os.environ["SMTP_PASS"] = "pass"
    os.environ["SMTP_FROM"] = "noreply@example.org"

    class DummySMTP:
        sent = []

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            self.started_tls = True

        def login(self, username, password):
            self.login_args = (username, password)

        def send_message(self, msg):
            DummySMTP.sent.append(msg)

    monkeypatch.setattr("smtplib.SMTP", DummySMTP)

    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    payload = {"message_html": "<p>Hallo <script>bad()</script><b>Team</b></p>"}
    resp = client.post("/api/feedback", json=payload, headers={"X-App-Secret": os.environ["APP_SECRET"]})
    assert resp.status_code == 200
    assert DummySMTP.sent
    msg = DummySMTP.sent[-1]
    html_part = msg.get_body(preferencelist=("html",))
    assert html_part is not None
    html_content = html_part.get_content()
    assert "<script" not in html_content
    assert "Team" in html_content


def test_feedback_length_limit(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    os.environ["FEEDBACK_ENABLED"] = "true"
    os.environ["FEEDBACK_TO"] = "team@example.org"
    os.environ["SMTP_HOST"] = "smtp.example.org"
    os.environ["SMTP_PORT"] = "25"
    os.environ["SMTP_USE_TLS"] = "false"
    os.environ["SMTP_FROM"] = "noreply@example.org"

    class DummySMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, msg):
            pass

    monkeypatch.setattr("smtplib.SMTP", DummySMTP)

    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    too_long = "x" * (MAX_FEEDBACK_CHARS + 1)
    resp = client.post("/api/feedback", json={"message_text": too_long}, headers={"X-App-Secret": os.environ["APP_SECRET"]})
    assert resp.status_code == 400
