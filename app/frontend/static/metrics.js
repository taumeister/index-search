const fmtMs = (v) => (v === null || v === undefined ? "–" : `${v.toFixed(1)} ms`);
const fmtTs = (ts) => {
    if (!ts) return "–";
    const d = new Date(ts * 1000);
    return d.toLocaleString();
};

async function loadSummary() {
    const endpoint = document.getElementById("metrics-endpoint").value || "";
    const windowSeconds = parseInt(document.getElementById("metrics-window").value, 10) || 86400;
    const testFlag = document.getElementById("metrics-testflag").value;
    const params = new URLSearchParams({ window_seconds: String(windowSeconds) });
    if (endpoint) params.append("endpoint", endpoint);
    if (testFlag === "real") params.append("is_test", "false");
    if (testFlag === "test") params.append("is_test", "true");
    const box = document.getElementById("metrics-summary");
    box.textContent = "Lade...";
    try {
        const res = await fetch(`/api/admin/metrics/summary?${params.toString()}`);
        if (!res.ok) {
            box.textContent = "Fehler beim Laden.";
            return;
        }
        const data = await res.json();
        renderSummary(box, data);
    } catch (err) {
        box.textContent = "Fehler beim Laden.";
    }
}

function renderSummary(el, data) {
    const totals = data.totals || {};
    const ttfb = data.ttfb || {};
    const first = data.smb_first_read || {};
    const transfer = data.transfer || {};
    const causes = data.causes || {};
    const causeItems = Object.entries(causes)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5)
        .map(([k, v]) => `${k || 'unknown'}: ${v}`)
        .join(", ");
    el.innerHTML = `
        <div class="metrics-grid">
            <div><div class="label">Events</div><div class="value">${data.count || 0}</div></div>
            <div><div class="label">Total p50/p95/p99</div><div class="value">${fmtMs(totals.p50 || 0)} / ${fmtMs(totals.p95 || 0)} / ${fmtMs(totals.p99 || 0)}</div></div>
            <div><div class="label">TTFB p50/p95/p99</div><div class="value">${fmtMs(ttfb.p50 || 0)} / ${fmtMs(ttfb.p95 || 0)} / ${fmtMs(ttfb.p99 || 0)}</div></div>
            <div><div class="label">SMB First Read p50/p95/p99</div><div class="value">${fmtMs(first.p50 || 0)} / ${fmtMs(first.p95 || 0)} / ${fmtMs(first.p99 || 0)}</div></div>
            <div><div class="label">Transfer p50/p95/p99</div><div class="value">${fmtMs(transfer.p50 || 0)} / ${fmtMs(transfer.p95 || 0)} / ${fmtMs(transfer.p99 || 0)}</div></div>
            <div><div class="label">Top Ursachen</div><div class="value">${causeItems || '–'}</div></div>
        </div>
    `;
}

async function loadEvents() {
    const limit = parseInt(document.getElementById("events-limit").value, 10) || 100;
    const testFlag = document.getElementById("metrics-testflag").value;
    const params = new URLSearchParams({ limit: String(limit) });
    if (testFlag === "real") params.append("is_test", "false");
    if (testFlag === "test") params.append("is_test", "true");
    const resBox = document.getElementById("metrics-events");
    resBox.textContent = "Lade...";
    try {
        const res = await fetch(`/api/admin/metrics/events?${params.toString()}`);
        if (!res.ok) {
            resBox.textContent = "Fehler beim Laden.";
            return;
        }
        const data = await res.json();
        renderEvents(resBox, data.events || []);
    } catch (err) {
        resBox.textContent = "Fehler beim Laden.";
    }
}

function renderEvents(el, events) {
    if (!events.length) {
        el.textContent = "Keine Events.";
        return;
    }
    const rows = events
        .map((ev) => {
            return `
                <tr>
                    <td>${fmtTs(ev.ts)}</td>
                    <td>${ev.endpoint || ''}</td>
                    <td>${ev.extension || ''}</td>
                    <td>${ev.size_bytes || ''}</td>
                    <td>${fmtMs(ev.server_total_ms)}</td>
                    <td>${fmtMs(ev.smb_first_read_ms)}</td>
                    <td>${fmtMs(ev.transfer_ms)}</td>
                    <td>${ev.cause || ''}</td>
                    <td>${ev.is_test ? 'test' : 'real'}</td>
                    <td>${ev.status_code || ''}</td>
                </tr>
            `;
        })
        .join("");
    el.innerHTML = `
        <table class="metrics-table">
            <thead>
                <tr>
                    <th>Zeit</th><th>Endpoint</th><th>Typ</th><th>Bytes</th><th>Total</th><th>SMB</th><th>Transfer</th><th>Ursache</th><th>Test</th><th>Status</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;
}

async function loadSystem() {
    const limit = parseInt(document.getElementById("system-limit").value, 10) || 240;
    const box = document.getElementById("metrics-system");
    box.textContent = "Lade...";
    try {
        const res = await fetch(`/api/admin/metrics/system?limit=${limit}`);
        if (!res.ok) {
            box.textContent = "Fehler beim Laden.";
            return;
        }
        const data = await res.json();
        renderSystem(box, data.slots || []);
    } catch (err) {
        box.textContent = "Fehler beim Laden.";
    }
}

function renderSystem(el, slots) {
    if (!slots.length) {
        el.textContent = "Keine System-Slots.";
        return;
    }
    const rows = slots
        .map((s) => {
            return `
                <tr>
                    <td>${fmtTs(s.slot_ts)}</td>
                    <td>${(s.cpu_percent ?? 0).toFixed(1)}%</td>
                    <td>${(s.mem_percent ?? 0).toFixed(1)}%</td>
                    <td>${(s.io_wait_percent ?? 0).toFixed(1)}%</td>
                    <td>${s.net_bytes_sent ?? 0}</td>
                    <td>${s.net_bytes_recv ?? 0}</td>
                </tr>
            `;
        })
        .join("");
    el.innerHTML = `
        <table class="metrics-table">
            <thead>
                <tr><th>Slot</th><th>CPU</th><th>RAM</th><th>iowait</th><th>Net Sent</th><th>Net Recv</th></tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;
}

function wireActions() {
    document.getElementById("metrics-refresh").addEventListener("click", loadSummary);
    document.getElementById("events-refresh").addEventListener("click", loadEvents);
    document.getElementById("system-refresh").addEventListener("click", loadSystem);
}

function bootstrap() {
    wireActions();
    loadSummary();
    loadEvents();
    loadSystem();
}

document.addEventListener("DOMContentLoaded", bootstrap);
