# Index-Report (Mail & Anhang)

## Überblick
- Der Index-Report wird nach einem Lauf per SMTP verschickt, wenn das Dashboard-Flag „Mail senden“ aktiv ist.
- Inhalt: KPIs (Added/Updated/Removed/Fehler), Details in Abschnitten (Added/Aktualisiert/Entfernt/Fehler) als `<details>`-Blöcke.
- Versand: HTML-Body (Inline) + vollständiger HTML-Anhang; Plaintext-Fallback bleibt erhalten.

## Theme
- Farben/Radien/Typo stammen aus den bestehenden Design-Tokens (`app/frontend/static/css/00-tokens.css`).
- Aktives Theme wird über `config_db`-Setting `theme` gelesen; Fallback ist `lumen-atelier`.

## Manuell einen Report generieren/senden
- Voraussetzung: `APP_SECRET`, SMTP in der Config, Run-ID existiert.
- Beispiel (lokal, Python):
  - `python - <<'PY'\nfrom app.config_loader import load_config\nfrom app import reporting\ncfg = load_config()\nreporting.send_run_report_email(cfg, run_id=123)\nprint(\"Report geschickt für Run 123\")\nPY`
- Nur HTML generieren (ohne Versand):
  - `python - <<'PY'\nfrom app.reporting import load_run_report_data, render_index_report\nrun_id = 123\ndata = load_run_report_data(run_id)\n_, inline_html, attachment_html, _ = render_index_report(data, theme_id=None, inline_limit=50)\nopen(\"test-artifacts/report-inline.html\", \"w\", encoding=\"utf-8\").write(inline_html)\nopen(\"test-artifacts/report-full.html\", \"w\", encoding=\"utf-8\").write(attachment_html)\nprint(\"Artefakte geschrieben\")\nPY`

## Anhänge/Struktur
- Dateiname: `index-report-<runid>-<date>.html`, MIME `text/html; charset=utf-8`.
- E-Mail multipart/alternative (Plain + HTML) plus Attachment (multipart/mixed).
