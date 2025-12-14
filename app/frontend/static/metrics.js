const authHeaders = { "X-Internal-Auth": "1" };

const state = {
    runs: [],
    currentRun: null,
    loading: false,
};

const fmtMs = (v) => (v === null || v === undefined ? "–" : `${v.toFixed(0)} ms`);
const fmtPct = (v) => (v === null || v === undefined ? "–" : `${v.toFixed(1)}%`);
const fmtRate = (v) => (v === null || v === undefined ? "–" : `${v.toFixed(1)}/min`);
const fmtMBs = (v) => (v === null || v === undefined ? "–" : `${v.toFixed(1)} MB/s`);
const fmtTs = (ts) => {
    if (!ts) return "–";
    const d = new Date(ts * 1000);
    return d.toLocaleString();
};

function setTab(tab) {
    document.querySelectorAll(".tab").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
    document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${tab}`));
}

async function fetchRuns() {
    const selector = document.getElementById("run-selector");
    selector.innerHTML = `<option>lade...</option>`;
    try {
        const res = await fetch("/api/admin/metrics/runs", { headers: authHeaders });
        if (!res.ok) {
            selector.innerHTML = `<option>Fehler</option>`;
            return;
        }
        const data = await res.json();
        state.runs = data.runs || [];
        selector.innerHTML = state.runs
            .map((r, idx) => `<option value="${r.run_id}" ${idx === 0 ? "selected" : ""}>${r.run_id} – ${fmtTs(r.created)}</option>`)
            .join("");
    } catch (err) {
        selector.innerHTML = `<option>Fehler</option>`;
    }
}

async function fetchRun(runId) {
    try {
        const url = runId ? `/api/admin/metrics/run/${encodeURIComponent(runId)}` : "/api/admin/metrics/run_latest";
        const res = await fetch(url, { headers: authHeaders });
        if (!res.ok) return null;
        const data = await res.json();
        state.currentRun = data;
        return data;
    } catch (err) {
        return null;
    }
}

function renderRunHeader(run) {
    const head = document.getElementById("run-headline");
    const meta = document.getElementById("run-meta");
    const status = document.getElementById("run-status");
    if (!run) {
        head.textContent = "Kein Run geladen";
        meta.textContent = "";
        status.textContent = "–";
        return;
    }
    const params = run.params || {};
    head.textContent = `Letzter Lauf: ${fmtTs(run.created)}`;
    const durMin = run.summary && run.summary.duration_sec ? (run.summary.duration_sec / 60).toFixed(1) : "–";
    meta.textContent = `Dataset: ${params.count || run.count || "?"} Docs ${params.ext_filter || ""} | Quelle: ${params.source || params.base || "?"} | Host: ${(run.environment || {}).host || "?"} | Dauer: ${durMin} min`;
    status.textContent = (run.diagnosis && run.diagnosis.overall) || "–";
    status.className = `pill status-pill ${run.diagnosis ? run.diagnosis.overall : ""}`;
}

function renderCauses(run) {
    const box = document.getElementById("cause-list");
    if (!run || !run.diagnosis) {
        box.textContent = "Keine Diagnose verfügbar.";
        return;
    }
    const causes = run.diagnosis.causes || [];
    box.innerHTML = causes
        .map(
            (c) => `
        <div class="cause-card ${c.status}">
            <div class="cause-head">
                <span class="status-dot ${c.status}"></span>
                <div class="cause-title">${c.label}</div>
            </div>
            <div class="cause-evidence">${(c.evidence || []).join(" · ") || "Keine Belege"}</div>
        </div>
    `
        )
        .join("");
}

function renderKPIs(run) {
    const grid = document.getElementById("kpi-grid");
    if (!run) {
        grid.textContent = "Keine Daten.";
        return;
    }
    const summary = run.summary || {};
    const cards = [
        { label: "Preview sichtbar (p95)", value: fmtMs((summary.totals || {}).p95), sub: `p50 ${fmtMs((summary.totals || {}).p50)}` },
        { label: "Previews/Min", value: fmtRate(summary.previews_per_min), sub: `${run.count || 0} Events im Run` },
        { label: "Fehlerquote", value: `${((summary.error_rate || 0) * 100).toFixed(1)}%`, sub: "HTTP >=400" },
        { label: "SMB Latenz", value: fmtMs((summary.smb_first_read || {}).p95), sub: `p50 ${fmtMs((summary.smb_first_read || {}).p50)}` },
        { label: "Durchsatz", value: fmtMBs((summary.throughput_mb_s || {}).p50), sub: "Transfer p50" },
    ];
    grid.innerHTML = cards
        .map(
            (c) => `
        <div class="kpi-card">
            <div class="label">${c.label}</div>
            <div class="value">${c.value}</div>
            <div class="sub">${c.sub}</div>
        </div>
    `
        )
        .join("");
}

function renderTimeline(run) {
    const box = document.getElementById("chart-timeline");
    const data = (run && run.timeline) || [];
    if (!data.length) {
        box.textContent = "Keine Daten.";
        return;
    }
    const max = Math.max(...data.map((d) => d.total_ms || 0), 1);
    box.innerHTML = data
        .map((d) => {
            const h = Math.min(100, ((d.total_ms || 0) / max) * 100);
            return `<div class="spark-bar" title="#${d.idx} – ${fmtMs(d.total_ms)}"><span style="height:${h}%"></span></div>`;
        })
        .join("");
}

function renderSmb(run) {
    const box = document.getElementById("chart-smb");
    const data = (run && run.timeline) || [];
    if (!data.length) {
        box.textContent = "Keine Daten.";
        return;
    }
    const max = Math.max(...data.map((d) => d.smb_ms || 0), 1);
    box.innerHTML = data
        .map((d) => {
            const h = Math.min(100, ((d.smb_ms || 0) / max) * 100);
            return `<div class="spark-bar" title="#${d.idx} – SMB ${fmtMs(d.smb_ms)}"><span style="height:${h}%"></span></div>`;
        })
        .join("");
}

function renderSystem(run) {
    const box = document.getElementById("chart-system");
    const slots = (run && run.system_slots) || [];
    if (!slots.length) {
        box.textContent = "Keine Daten.";
        return;
    }
    const cpuMax = Math.max(...slots.map((s) => s.cpu_percent || 0), 1);
    const memMax = Math.max(...slots.map((s) => s.mem_percent || 0), 1);
    box.innerHTML = `
        <div class="sparkline">${renderSpark(slots.map((s) => s.cpu_percent || 0), cpuMax, "CPU")}</div>
        <div class="sparkline">${renderSpark(slots.map((s) => s.mem_percent || 0), memMax, "RAM")}</div>
    `;
}

function renderSpark(values, max, label) {
    if (!values.length) return "–";
    const height = 60;
    const maxVal = Math.max(max, 1);
    const bars = values
        .map((v) => `<div class="spark-bar" title="${label} ${fmtPct(v)}"><span style="height:${Math.min(100, (v / maxVal) * 100)}%"></span></div>`)
        .join("");
    return `<div class="spark-head">${label}</div><div class="spark-group">${bars}</div>`;
}

function renderPipeline(run) {
    const box = document.getElementById("pipeline-bars");
    const summary = (run && run.summary) || {};
    const steps = [
        { label: "TTFB", data: summary.ttfb },
        { label: "SMB First Read", data: summary.smb_first_read },
        { label: "Transfer", data: summary.transfer },
        { label: "Gesamt", data: summary.totals },
    ];
    const max = Math.max(...steps.map((s) => (s.data && s.data.p95) || 0), 1);
    box.innerHTML = steps
        .map((s) => {
            const p50 = (s.data && s.data.p50) || 0;
            const p95 = (s.data && s.data.p95) || 0;
            return `
            <div class="pipe-row">
                <div class="pipe-label">${s.label}</div>
                <div class="pipe-bar">
                    <span class="bar-50" style="width:${Math.min(100, (p50 / max) * 100)}%"></span>
                    <span class="bar-95" style="width:${Math.min(100, (p95 / max) * 100)}%"></span>
                </div>
                <div class="pipe-values">p50 ${fmtMs(p50)} / p95 ${fmtMs(p95)}</div>
            </div>
        `;
        })
        .join("");
}

function renderEvents(run) {
    const box = document.getElementById("metrics-events");
    const events = (run && run.events) || [];
    if (!events.length) {
        box.textContent = "Keine Events.";
        return;
    }
    const rows = events
        .map(
            (ev) => `
        <tr>
            <td>${fmtTs(ev.ts)}</td>
            <td>${ev.extension || ""}</td>
            <td>${ev.size_bytes || ""}</td>
            <td>${fmtMs(ev.server_total_ms)}</td>
            <td>${fmtMs(ev.smb_first_read_ms)}</td>
            <td>${fmtMs(ev.transfer_ms)}</td>
            <td>${ev.cause || ""}</td>
            <td>${ev.status_code || ""}</td>
        </tr>`
        )
        .join("");
    box.innerHTML = `
        <table class="metrics-table">
            <thead><tr><th>Zeit</th><th>Typ</th><th>Bytes</th><th>Total</th><th>SMB</th><th>Transfer</th><th>Ursache</th><th>Status</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>
    `;
}

function renderSystemTable(run) {
    const box = document.getElementById("metrics-system");
    const slots = (run && run.system_slots) || [];
    if (!slots.length) {
        box.textContent = "Keine Slots.";
        return;
    }
    const rows = slots
        .map(
            (s) => `
        <tr>
            <td>${fmtTs(s.slot_ts)}</td>
            <td>${fmtPct(s.cpu_percent)}</td>
            <td>${fmtPct(s.mem_percent)}</td>
            <td>${fmtPct(s.io_wait_percent)}</td>
            <td>${s.net_bytes_recv || 0}</td>
            <td>${fmtMBs((s.disk_read_bytes || 0) / 1024 / 1024)}</td>
        </tr>`
        )
        .join("");
    box.innerHTML = `
        <table class="metrics-table">
            <thead><tr><th>Slot</th><th>CPU</th><th>RAM</th><th>iowait</th><th>Net Recv</th><th>Disk Read</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>
    `;
}

async function loadSelectedRun() {
    const selector = document.getElementById("run-selector");
    const runId = selector.value;
    const run = await fetchRun(runId);
    renderAll(run);
}

function renderAll(run) {
    renderRunHeader(run);
    renderCauses(run);
    renderKPIs(run);
    renderTimeline(run);
    renderSmb(run);
    renderSystem(run);
    renderPipeline(run);
    renderEvents(run);
    renderSystemTable(run);
}

async function startTestRun() {
    const btn = document.getElementById("test-run");
    const status = document.getElementById("test-status");
    const count = parseInt(document.getElementById("test-count").value, 10) || 200;
    const ext = document.getElementById("test-ext").value || "";
    const minSize = parseFloat(document.getElementById("test-min-size").value) || 0;
    btn.disabled = true;
    status.textContent = "Starte Test...";
    try {
        const res = await fetch(
            "/api/admin/metrics/test_run?" +
                new URLSearchParams({
                    count: String(count),
                    ext_filter: ext,
                    min_size_mb: String(minSize),
                }),
            { method: "POST", headers: authHeaders }
        );
        if (!res.ok) {
            status.textContent = res.status === 409 ? "Test läuft bereits." : "Fehler beim Start.";
            return;
        }
        const data = await res.json();
        status.textContent = `Run ${data.test_run_id} gestartet`;
        setTimeout(async () => {
            await fetchRuns();
            await loadSelectedRun();
            status.textContent = "Test aktualisiert.";
        }, 5000);
    } catch (err) {
        status.textContent = "Fehler beim Start.";
    } finally {
        setTimeout(() => {
            btn.disabled = false;
        }, 2000);
    }
}

function wireUi() {
    document.querySelectorAll(".tab").forEach((btn) => btn.addEventListener("click", () => setTab(btn.dataset.tab)));
    document.getElementById("metrics-refresh").addEventListener("click", loadSelectedRun);
    document.getElementById("test-run").addEventListener("click", startTestRun);
    document.getElementById("run-selector").addEventListener("change", loadSelectedRun);
}

async function bootstrap() {
    wireUi();
    await fetchRuns();
    await loadSelectedRun();
}

document.addEventListener("DOMContentLoaded", bootstrap);
