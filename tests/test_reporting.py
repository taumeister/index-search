from app import config_db, reporting
from app.config_loader import SMTPConfig, load_config


def sample_run_data():
    return {
        "run": {
            "id": 5,
            "started_at": "2024-01-01T10:00:00+00:00",
            "finished_at": "2024-01-01T10:05:00+00:00",
            "status": "completed",
            "added": 3,
            "updated": 2,
            "removed": 1,
            "errors": 1,
        },
        "actions": {"added": 3, "updated": 2, "removed": 1},
        "events": {
            "added": [
                {"path": "/a/one.pdf", "source": "srcA", "ts": "2024-01-01T10:00:10+00:00", "message": ""},
                {"path": "/a/two.pdf", "source": "srcA", "ts": "2024-01-01T10:00:20+00:00", "message": ""},
                {"path": "/a/three.pdf", "source": "srcA", "ts": "2024-01-01T10:00:30+00:00", "message": ""},
            ],
            "updated": [
                {"path": "/b/one.pdf", "source": "srcB", "ts": "2024-01-01T10:01:00+00:00", "message": "mtime changed"},
            ],
            "removed": [
                {"path": "/c/old.pdf", "source": "srcC", "ts": "2024-01-01T10:02:00+00:00", "message": "removed"},
            ],
        },
        "errors": [
            {"path": "/err/file.pdf", "error_type": "PdfError", "message": "failed", "created_at": "2024-01-01T10:03:00+00:00", "ignored": 0}
        ],
    }


def test_render_index_report_limit_and_theme():
    _, inline_html, attachment_html, plain_text = reporting.render_index_report(sample_run_data(), theme_id="marble-coast", inline_limit=2)
    assert "Run #5" in inline_html
    assert "marble-coast" in inline_html
    assert "#1f6e8f" in inline_html  # accent color from theme gradient
    assert "Weitere 1 Einträge im Anhang" in inline_html
    assert "/a/three.pdf" not in inline_html
    assert "/a/three.pdf" in attachment_html
    assert "Fehler" in inline_html
    assert "Details: Siehe HTML-Mail" in plain_text


def test_build_report_email_structure():
    _, inline_html, attachment_html, plain_text = reporting.render_index_report(sample_run_data(), theme_id="lumen-atelier", inline_limit=1)
    msg = reporting.build_report_email(
        sender="noreply@example.org",
        recipients=["team@example.org"],
        subject="Index-Report",
        inline_html=inline_html,
        plain_text=plain_text,
        attachment_html=attachment_html,
        attachment_name="index-report.html",
    )
    assert msg.is_multipart()
    attach_list = list(msg.iter_attachments())
    assert len(attach_list) == 1
    attachment = attach_list[0]
    assert attachment.get_filename() == "index-report.html"
    assert attachment.get_content_type() == "text/html"
    alt = msg.get_body(preferencelist=("html",))
    assert alt is not None
    assert inline_html in alt.get_content()


def test_send_run_report_email(monkeypatch, tmp_path):
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    config_db.ensure_db()
    config_db.set_setting("send_report_enabled", "1")
    sent_msgs = []

    def fake_load(run_id: int):
        data = sample_run_data()
        data["run"]["id"] = run_id
        return data

    class DummySMTP:
        def __init__(self, host, port, timeout=10):
            self.host = host
            self.port = port
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            self.started_tls = True

        def login(self, username, password):
            self.login_args = (username, password)

        def send_message(self, msg):
            sent_msgs.append(msg)

    monkeypatch.setattr(reporting, "load_run_report_data", fake_load)
    monkeypatch.setattr("smtplib.SMTP", DummySMTP)

    cfg = load_config(use_env=False)
    cfg.smtp = SMTPConfig(
        host="smtp.test.local",
        port=2525,
        use_tls=False,
        username=None,
        password=None,
        sender="noreply@test.local",
        recipients=["ops@test.local"],
    )

    reporting.send_run_report_email(cfg, run_id=9)
    assert sent_msgs, "Report-Mail wurde nicht gesendet"
    msg = sent_msgs[-1]
    assert msg["Subject"] is not None
    assert msg.get_body(preferencelist=("html",)) is not None
    attachments = list(msg.iter_attachments())
    assert attachments and attachments[0].get_content_type() == "text/html"
