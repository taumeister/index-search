let currentDocId = null;
let searchTimer = null;
let currentSearchController = null;
let sortState = { key: null, dir: "asc" };
let resizingColumn = false;
let resizingPreview = false;
const PANEL_WIDTH_KEY = "previewWidth";
const APP_ZOOM_KEY = "appZoom";
const DEFAULT_ZOOM = 1;
const MIN_ZOOM = 0.6;
const MAX_ZOOM = 1.6;
const ZOOM_STEP = 0.1;
const SEARCH_LIMIT = 200;
const MIN_QUERY_LENGTH = 2;
const SEARCH_DEBOUNCE_MS = 400;
let searchOffset = 0;
let searchHasMore = false;
let searchLoading = false;
const METRICS_ENABLED = true;
const dateFormatter = new Intl.DateTimeFormat("de-DE", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
});
const SUPPORTED_EXTENSIONS = ["", ".pdf", ".rtf", ".msg", ".txt"];

function escapeHtml(str) {
    return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

applySavedPreviewWidth();
bootstrapZoom();

async function search({ append = false } = {}) {
    const q = document.getElementById("search-input").value || "";
    const trimmed = q.trim();
    const ext = document.getElementById("ext-filter").value;
    const time = document.getElementById("time-filter").value;

    if (!append) {
        searchOffset = 0;
        searchHasMore = false;
    }

    if (trimmed && trimmed.length < MIN_QUERY_LENGTH) {
        searchHasMore = false;
        renderMessageRow(`Mindestens ${MIN_QUERY_LENGTH} Zeichen eingeben.`);
        updateLoadMoreButton();
        return;
    }

    if (currentSearchController) {
        currentSearchController.abort();
    }
    currentSearchController = new AbortController();

    const params = new URLSearchParams({ q, limit: SEARCH_LIMIT, offset: append ? searchOffset : 0 });
    if (ext) params.append("extension", ext.toLowerCase());
    if (time) params.append("time_filter", time);
    if (sortState.key) {
        params.append("sort_key", sortState.key);
        params.append("sort_dir", sortState.dir);
    }

    searchLoading = true;
    updateLoadMoreButton();

    try {
        const res = await fetch(`/api/search?${params.toString()}`, { signal: currentSearchController.signal });
        if (!res.ok) {
            searchHasMore = false;
            renderMessageRow("Suche fehlgeschlagen.");
            return;
        }
        const data = await res.json();
        const rows = data.results || [];
        searchHasMore = Boolean(data.has_more);
        if (data.message && !rows.length) {
            searchHasMore = false;
            renderMessageRow(data.message);
            updateLoadMoreButton();
            return;
        }
        renderResults(rows, { append });
        searchOffset = append ? searchOffset + rows.length : rows.length;
        if (!append) {
            populateFilters(rows);
        }
        updateSortIndicators();
    } catch (err) {
        if (err.name === "AbortError") return;
        searchHasMore = false;
        renderMessageRow("Suche abgebrochen oder fehlgeschlagen.");
    } finally {
        if (currentSearchController && currentSearchController.signal.aborted) {
            // nichts
        }
        searchLoading = false;
        updateLoadMoreButton();
    }
}

function debounceSearch() {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => search({ append: false }), SEARCH_DEBOUNCE_MS);
}

async function sendClientMetric(payload) {
    if (!METRICS_ENABLED) return;
    try {
        await fetch("/api/admin/metrics/client_event", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
    } catch (err) {
        // best-effort, keine UI-Störung
    }
}

function renderResults(results, { append = false } = {}) {
    const tbody = document.querySelector("#results-table tbody");
    if (!append) {
        tbody.innerHTML = "";
    }
    if (!results.length && !append) {
        renderMessageRow("Keine Treffer gefunden.");
        return;
    }

    results.forEach((row) => {
        const tr = document.createElement("tr");
        const rowId = row.id || row.doc_id;
        tr.dataset.id = rowId;
        const sizeLabel = typeof row.size_bytes === "number" ? `${(row.size_bytes / 1024).toFixed(1)} KB` : "–";
        const mtimeLabel = row.mtime ? dateFormatter.format(new Date(row.mtime * 1000)) : "–";
        const pathLabel = row.path || "";
        const nameLabel = row.filename || "";
        const snippetText = row.snippet ? stripTags(row.snippet) : "";
        const snippetHtml = sanitizeSnippet(row.snippet);
        tr.innerHTML = `
            <td class="cell-name" title="${escapeHtml(nameLabel)}">
                <span class="filename">${escapeHtml(nameLabel)}</span>
            </td>
            <td class="snippet" title="${escapeHtml(snippetText)}">${snippetHtml || ""}</td>
            <td>${escapeHtml(mtimeLabel)}</td>
            <td>${escapeHtml(sizeLabel)}</td>
            <td>${escapeHtml(row.extension)}</td>
            <td class="path-cell" title="${escapeHtml(pathLabel)}">${escapeHtml(pathLabel)}</td>
        `;
        if (currentDocId && String(currentDocId) === String(rowId)) {
            tr.classList.add("active");
        }
        tr.addEventListener("click", () => {
            markActiveRow(rowId);
            openPreview(rowId, true);
        });
        tr.addEventListener("dblclick", () => openPopupForRow(rowId));
        tr.addEventListener("contextmenu", (e) => showContextMenu(e, rowId));
        tbody.appendChild(tr);
    });
}

function renderMessageRow(text) {
    const tbody = document.querySelector("#results-table tbody");
    if (tbody) {
        tbody.innerHTML = `<tr><td class="empty-row" colspan="6">${escapeHtml(text)}</td></tr>`;
    }
}

function updateLoadMoreButton() {
    const btn = document.getElementById("load-more");
    if (!btn) return;
    btn.disabled = searchLoading;
    btn.classList.toggle("hidden", !searchHasMore);
}

async function openPreview(id, showPanel = false) {
    if (!id) return;
    currentDocId = id;
    markActiveRow(id);
    const clickWallTs = Date.now() / 1000;
    const clickPerf = performance.now();
    const res = await fetch(`/api/document/${id}`);
    const respHeadersPerf = performance.now();
    if (!res.ok) {
        closePreviewPanel();
        return;
    }
    const doc = await res.json();
    const respEndPerf = performance.now();
    if (currentDocId !== id) return;
    document.getElementById("download-link").href = `/api/document/${id}/file?download=1`;
    const renderDone = () => {
        if (!METRICS_ENABLED) return;
        const renderPerf = performance.now();
        const base = clickWallTs;
        sendClientMetric({
            doc_id: id,
            size_bytes: doc.size_bytes,
            extension: doc.extension,
            client_click_ts: base,
            client_resp_start_ts: base + (respHeadersPerf - clickPerf) / 1000,
            client_resp_end_ts: base + (respEndPerf - clickPerf) / 1000,
            client_render_end_ts: base + (renderPerf - clickPerf) / 1000,
        });
    };
    renderPreviewContent(doc, document.getElementById("preview-content"), renderDone);
    updatePreviewHeader(doc);
    if (showPanel) {
        showPreviewPanel();
    }
}

function showPreviewPanel() {
    document.getElementById("preview-panel").classList.remove("hidden");
    positionPreview();
}

function closePreviewPanel() {
    document.getElementById("preview-panel").classList.add("hidden");
    markActiveRow(null);
    currentDocId = null;
    resetPreviewHeader();
}

function previewIsOpen() {
    return !document.getElementById("preview-panel").classList.contains("hidden");
}

function getPanelWidthPx() {
    const raw = getComputedStyle(document.documentElement).getPropertyValue("--panel-width").trim();
    const numeric = parseFloat(raw);
    return Number.isFinite(numeric) ? numeric : 360;
}

function clampPanelWidth(px) {
    const min = 260;
    const max = Math.max(min + 120, window.innerWidth - 320);
    return Math.min(Math.max(px, min), max);
}

function setPanelWidth(px) {
    const value = clampPanelWidth(px);
    document.documentElement.style.setProperty("--panel-width", `${value}px`);
    positionPreview();
}

function applySavedPreviewWidth() {
    const saved = sessionStorage.getItem(PANEL_WIDTH_KEY);
    if (!saved) return;
    const parsed = parseFloat(saved);
    if (!Number.isFinite(parsed)) return;
    setPanelWidth(parsed);
}

function positionPreview() {
    const panel = document.getElementById("preview-panel");
    const results = document.getElementById("results-pane");
    if (!panel || !results || panel.classList.contains("hidden")) return;
    const rect = results.getBoundingClientRect();
    const panelWidth = getPanelWidthPx();
    const left = Math.max(rect.right - panelWidth, rect.left + 8);
    panel.style.width = `${panelWidth}px`;
    panel.style.left = `${left}px`;
    panel.style.right = "auto";
    panel.style.top = `${rect.top}px`;
    const height = Math.max(200, window.innerHeight - rect.top - 12);
    panel.style.height = `${height}px`;
}

function markActiveRow(id) {
    document.querySelectorAll("#results-table tbody tr").forEach((tr) => {
        tr.classList.toggle("active", id && String(tr.dataset.id) === String(id));
    });
}

function setupPreviewResizer() {
    const handle = document.getElementById("preview-resizer");
    if (!handle) return;
    let startX = 0;
    let startWidth = 0;

    const onDrag = (e) => {
        const delta = startX - e.clientX;
        const newWidth = startWidth + delta;
        setPanelWidth(newWidth);
        positionPreview();
    };

    const stopDrag = () => {
        document.removeEventListener("mousemove", onDrag);
        document.removeEventListener("mouseup", stopDrag);
        document.body.classList.remove("resizing-preview");
        sessionStorage.setItem(PANEL_WIDTH_KEY, String(getPanelWidthPx()));
        setTimeout(() => {
            resizingPreview = false;
        }, 50);
    };

    handle.addEventListener("mousedown", (e) => {
        if (!previewIsOpen()) return;
        resizingPreview = true;
        startX = e.clientX;
        startWidth = getPanelWidthPx();
        document.body.classList.add("resizing-preview");
        document.addEventListener("mousemove", onDrag);
        document.addEventListener("mouseup", stopDrag);
        e.preventDefault();
    });
}

function renderPreviewContent(doc, container, onRenderComplete) {
    container.innerHTML = "";
    const ext = (doc.extension || "").toLowerCase();
    if (ext === ".pdf") {
        const iframe = document.createElement("iframe");
        iframe.src = `/api/document/${doc.id}/file#toolbar=0&navpanes=0&view=FitH`;
        iframe.className = "pdf-frame";
        iframe.addEventListener("load", () => {
            if (typeof onRenderComplete === "function") onRenderComplete();
        });
        container.appendChild(iframe);
        setTimeout(() => {
            if (typeof onRenderComplete === "function") onRenderComplete();
        }, 15000);
        return;
    }

    if (ext === ".msg") {
        const header = document.createElement("div");
        header.innerHTML = `
            <div><strong>Von:</strong> ${escapeHtml(doc.msg_from || "")}</div>
            <div><strong>An:</strong> ${escapeHtml(doc.msg_to || "")}</div>
            <div><strong>CC:</strong> ${escapeHtml(doc.msg_cc || "")}</div>
            <div><strong>Betreff:</strong> ${escapeHtml(doc.msg_subject || doc.title_or_subject || "")}</div>
            <div><strong>Datum:</strong> ${escapeHtml(doc.msg_date || "")}</div>
            <hr/>
        `;
        const body = document.createElement("pre");
        body.innerHTML = highlightTerms(doc.content || "");
        container.appendChild(header);
        container.appendChild(body);
        if (typeof onRenderComplete === "function") onRenderComplete();
        return;
    }

    const pre = document.createElement("pre");
    pre.innerHTML = highlightTerms(doc.content || "");
    container.appendChild(pre);
    if (typeof onRenderComplete === "function") onRenderComplete();
}

function stripTags(html) {
    const tmp = document.createElement("div");
    tmp.innerHTML = html || "";
    return tmp.textContent || "";
}

function sanitizeSnippet(html) {
    const tmp = document.createElement("div");
    tmp.innerHTML = html || "";
    const clean = (node) => {
        Array.from(node.childNodes).forEach((child) => {
            if (child.nodeType === Node.TEXT_NODE) return;
            if (child.nodeType === Node.ELEMENT_NODE) {
                if (child.tagName === "MARK") {
                    clean(child);
                } else {
                    const text = document.createTextNode(child.textContent || "");
                    node.replaceChild(text, child);
                }
            } else {
                node.removeChild(child);
            }
        });
    };
    clean(tmp);
    return tmp.innerHTML;
}

function getCurrentTerms() {
    const q = document.getElementById("search-input")?.value || "";
    return q
        .split(/[\s,]+/)
        .map((t) => t.trim())
        .filter(Boolean)
        .slice(0, 5);
}

function highlightTerms(text) {
    const terms = getCurrentTerms();
    if (!terms.length || !text) return escapeHtml(text);
    const slice = text.slice(0, 80000); // Limit für Performance
    const regex = new RegExp(`(${terms.map((t) => escapeRegExp(t)).join("|")})`, "gi");
    return escapeHtml(slice).replace(regex, "<mark>$1</mark>");
}

function escapeRegExp(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function openPopupForRow(id) {
    if (!id) return;
    const url = `/viewer?id=${id}`;
    const w = Math.max(520, Math.floor(window.screen.availWidth * 0.45));
    const h = Math.max(480, Math.floor(window.screen.availHeight * 0.58));
    const left = Math.floor((window.screen.availWidth - w) / 2);
    const top = Math.floor((window.screen.availHeight - h) / 2);
    window.open(
        url,
        "_blank",
        `width=${w},height=${h},left=${left},top=${top},resizable=yes,scrollbars=yes,toolbar=no,location=no,menubar=no`
    );
}

function printDocument(id) {
    if (!id) return;
    const url = `/api/document/${id}/file#toolbar=0&navpanes=0&view=FitH`;
    const iframe = document.createElement("iframe");
    iframe.style.position = "fixed";
    iframe.style.right = "-9999px";
    iframe.style.width = "1px";
    iframe.style.height = "1px";
    iframe.src = url;
    const cleanup = () => setTimeout(() => iframe.remove(), 800);
    iframe.onload = () => {
        try {
            iframe.contentWindow.focus();
            iframe.contentWindow.print();
        } catch (err) {
            console.error("Print fehlgeschlagen", err);
        } finally {
            cleanup();
        }
    };
    document.body.appendChild(iframe);
}

function updatePreviewHeader(doc) {
    const nameEl = document.getElementById("preview-name");
    const pathEl = document.getElementById("preview-path");
    if (nameEl) {
        nameEl.textContent = doc.filename || doc.title_or_subject || "Preview";
    }
    if (pathEl) {
        pathEl.textContent = doc.path || "";
    }
}

function resetPreviewHeader() {
    const nameEl = document.getElementById("preview-name");
    const pathEl = document.getElementById("preview-path");
    if (nameEl) nameEl.textContent = "Preview";
    if (pathEl) pathEl.textContent = "";
}

function setupPopup() {
    document.getElementById("open-popup").addEventListener("click", () => {
        if (!currentDocId) return;
        openPopupForRow(currentDocId);
    });
    document.getElementById("print-doc").addEventListener("click", () => {
        if (!currentDocId) return;
        printDocument(currentDocId);
    });
}

// Search & filter bindings
document.getElementById("search-input").addEventListener("input", debounceSearch);
document.getElementById("ext-filter").addEventListener("change", () => search({ append: false }));
document.getElementById("time-filter").addEventListener("change", () => search({ append: false }));
const loadMoreBtn = document.getElementById("load-more");
if (loadMoreBtn) {
    loadMoreBtn.addEventListener("click", () => {
        if (searchHasMore && !searchLoading) {
            search({ append: true });
        }
    });
}

setupPopup();
setupPreviewResizer();

// Column resize
function setupResizableColumns() {
    const headerRow = document.querySelector("#results-table thead tr");
    const stored = JSON.parse(localStorage.getItem("colWidths") || "{}");
    headerRow.querySelectorAll("th").forEach((th, index) => {
        th.style.position = "relative";
        if (stored[index]) {
            th.style.width = stored[index];
        } else if (th.dataset.width) {
            th.style.width = th.dataset.width;
        }
        const handle = document.createElement("div");
        handle.className = "resize-handle";
        let startX = 0;
        let startWidth = 0;
        handle.addEventListener("click", (e) => e.stopPropagation());
        handle.addEventListener("mousedown", (e) => {
            resizingColumn = true;
            startX = e.clientX;
            startWidth = th.offsetWidth;
            document.addEventListener("mousemove", onDrag);
            document.addEventListener("mouseup", stopDrag);
            e.preventDefault();
        });
        function onDrag(e) {
            const newWidth = Math.max(40, startWidth + (e.clientX - startX));
            th.style.width = `${newWidth}px`;
        }
        function stopDrag() {
            document.removeEventListener("mousemove", onDrag);
            document.removeEventListener("mouseup", stopDrag);
            const widths = {};
            headerRow.querySelectorAll("th").forEach((th2, idx) => {
                if (th2.style.width) widths[idx] = th2.style.width;
            });
            localStorage.setItem("colWidths", JSON.stringify(widths));
            setTimeout(() => {
                resizingColumn = false;
            }, 50);
        }
        th.appendChild(handle);
    });
}

// Context menu
let contextMenuEl = null;
function showContextMenu(e, id) {
    e.preventDefault();
    closeContextMenu();
    const menu = document.createElement("div");
    menu.className = "context-menu";
    const ul = document.createElement("ul");
    ul.innerHTML = `
        <li data-action="preview">Preview</li>
        <li data-action="popup">Pop-up</li>
        <li data-action="download">Download</li>
        <li data-action="print">Drucken</li>
    `;
    ul.addEventListener("click", (ev) => {
        const action = ev.target.dataset.action;
        if (action === "preview") openPreview(id, true);
        if (action === "popup") openPopupForRow(id);
        if (action === "download") window.open(`/api/document/${id}/file?download=1`, "_blank");
        if (action === "print") printDocument(id);
        closeContextMenu();
    });
    menu.appendChild(ul);
    document.body.appendChild(menu);
    menu.style.left = `${e.clientX}px`;
    menu.style.top = `${e.clientY}px`;
    contextMenuEl = menu;
    document.addEventListener("click", closeContextMenu, { once: true });
}

function closeContextMenu() {
    if (contextMenuEl) {
        contextMenuEl.remove();
        contextMenuEl = null;
    }
}

window.addEventListener("load", setupResizableColumns);
initZoomControls();

function populateFilters(results) {
    const extSelect = document.getElementById("ext-filter");
    const currentExt = extSelect.value;
    const extOptions = SUPPORTED_EXTENSIONS.map((x) => {
        if (!x) return '<option value="">Typ (alle / Reset)</option>';
        return `<option value="${x}">${x}</option>`;
    });
    extSelect.innerHTML = extOptions.join("");
    extSelect.value = currentExt;
}

// Sorting
const sortableKeys = new Set(["filename", "extension", "size_bytes", "mtime"]);
document.querySelectorAll("#results-table th").forEach((th) => {
    const key = th.dataset.key;
    if (!key || !sortableKeys.has(key)) {
        th.classList.add("not-sortable");
        return;
    }
    th.classList.add("sortable");
    th.addEventListener("click", () => {
        if (resizingColumn) return;
        if (sortState.key === key) {
            sortState.dir = sortState.dir === "asc" ? "desc" : "asc";
        } else {
            sortState.key = key;
            sortState.dir = "asc";
        }
        updateSortIndicators();
        search();
    });
});

function updateSortIndicators() {
    document.querySelectorAll("#results-table th").forEach((th) => {
        th.classList.remove("sort-asc", "sort-desc");
        if (th.dataset.key === sortState.key) {
            th.classList.add(sortState.dir === "desc" ? "sort-desc" : "sort-asc");
        }
    });
}

// Close preview when clicking outside preview/table
document.addEventListener("click", (e) => {
    if (resizingPreview) return;
    if (!previewIsOpen()) return;
    if (e.target.closest("#preview-panel")) return;
    if (e.target.closest("#results-table")) return;
    if (e.target.closest("#results-pane")) return;
    if (e.target.closest(".context-menu")) return;
    closePreviewPanel();
});

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        closePreviewPanel();
        closeContextMenu();
    }
});

window.addEventListener("resize", positionPreview);

function clampZoom(value) {
    return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function readSavedZoom() {
    try {
        const raw = localStorage.getItem(APP_ZOOM_KEY);
        const parsed = parseFloat(raw);
        if (Number.isFinite(parsed)) {
            return clampZoom(parsed);
        }
    } catch (_) {
        /* ignore */
    }
    return DEFAULT_ZOOM;
}

function getActiveZoom() {
    const raw = getComputedStyle(document.documentElement).getPropertyValue("--app-zoom");
    const parsed = parseFloat(raw);
    if (Number.isFinite(parsed)) return clampZoom(parsed);
    return readSavedZoom();
}

function applyZoom(value, { persist = true } = {}) {
    const clamped = clampZoom(value);
    document.documentElement.style.setProperty("--app-zoom", clamped);
    if (persist) {
        try {
            localStorage.setItem(APP_ZOOM_KEY, String(clamped));
        } catch (_) {
            /* ignore */
        }
    }
    updateZoomDisplay(clamped);
    positionPreview();
    return clamped;
}

function updateZoomDisplay(value) {
    const label = document.getElementById("zoom-display");
    if (!label) return;
    label.textContent = `${Math.round(value * 100)}%`;
}

function initZoomControls() {
    const initialZoom = readSavedZoom();
    applyZoom(initialZoom, { persist: false });

    const zoomIn = document.getElementById("zoom-in");
    const zoomOut = document.getElementById("zoom-out");
    const zoomReset = document.getElementById("zoom-reset");

    const adjustZoom = (delta) => {
        const next = clampZoom(getActiveZoom() + delta);
        applyZoom(next);
    };

    if (zoomIn) {
        zoomIn.addEventListener("click", () => adjustZoom(ZOOM_STEP));
    }
    if (zoomOut) {
        zoomOut.addEventListener("click", () => adjustZoom(-ZOOM_STEP));
    }
    if (zoomReset) {
        zoomReset.addEventListener("click", () => applyZoom(DEFAULT_ZOOM));
    }

    window.addEventListener("storage", (e) => {
        if (e.key === APP_ZOOM_KEY) {
            applyZoom(readSavedZoom(), { persist: false });
        }
    });
}

function bootstrapZoom() {
    applyZoom(readSavedZoom(), { persist: false });
}
