let currentDocId = null;
let searchTimer = null;
let currentSearchController = null;
let sortState = { key: null, dir: "asc" };
let resizingColumn = false;
let resizingPreview = false;
let feedbackState = { open: false, sending: false };
let feedbackRefs = {};
let suppressAutoFocus = false;
let viewerPopupRef = null;
let viewerPopupMonitor = null;
const PANEL_WIDTH_KEY = "previewWidth";
const APP_ZOOM_KEY = "appZoom";
const DEFAULT_ZOOM = 1;
const MIN_ZOOM = 0.6;
const MAX_ZOOM = 1.6;
const ZOOM_STEP = 0.1;
const SEARCH_LIMIT = 200;
const MIN_QUERY_LENGTH = 2;
const SEARCH_DEBOUNCE_MS = 400;
const SEARCH_MODE_KEY = "searchMode";
const SEARCH_MODE_SET = new Set(["strict", "standard", "loose"]);
const DEFAULT_SEARCH_MODE = normalizeSearchMode(window.searchDefaultMode) || "standard";
const TYPE_FILTER_KEY = "searchTypeFilter";
const TYPE_FILTER_SET = new Set(["", ".pdf", ".rtf", ".msg", ".txt"]);
const TIME_FILTER_KEY = "searchTimeFilter";
const TIME_YEAR_MAX = 2025;
const TIME_YEAR_MIN = 2000;
const TIME_PRIMARY_OPTIONS = ["", "yesterday", "last7", "last30"];
const TIME_MORE_OPTIONS = ["last365", ...Array.from({ length: TIME_YEAR_MAX - TIME_YEAR_MIN + 1 }, (_, i) => String(TIME_YEAR_MAX - i))];
const TIME_FILTER_ORDER = [...TIME_PRIMARY_OPTIONS, ...TIME_MORE_OPTIONS];
let searchOffset = 0;
let searchHasMore = false;
let searchLoading = false;
let currentSearchMode = DEFAULT_SEARCH_MODE;
let currentTypeFilter = "";
let currentTimeFilter = "";
const METRICS_ENABLED = true;
const FEEDBACK_ENABLED = Boolean(window.feedbackEnabled);
const FEEDBACK_MAX_LEN = 5000;
const FEEDBACK_ALLOWED_TAGS = new Set(["P", "DIV", "BR", "STRONG", "B", "EM", "I", "UL", "OL", "LI", "SPAN"]);
const FEEDBACK_SUBJECT = `Feedback zur Dokumenten-Volltext-Suche (${window.appVersion || "v?"})`;
const dateFormatter = new Intl.DateTimeFormat("de-DE", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
});

function escapeHtml(str) {
    return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function setSuppressAutoFocus(active) {
    suppressAutoFocus = Boolean(active);
    if (suppressAutoFocus) {
        window.clearTimeout(scheduleFocusSearchInput._t);
    }
}

function viewerIsOpen() {
    return viewerPopupRef && !viewerPopupRef.closed;
}

function trackViewerPopup(win) {
    viewerPopupRef = win && !win.closed ? win : null;
    setSuppressAutoFocus(Boolean(viewerPopupRef));
    if (viewerPopupMonitor) {
        window.clearInterval(viewerPopupMonitor);
        viewerPopupMonitor = null;
    }
    if (!viewerPopupRef) {
        setSuppressAutoFocus(false);
        return;
    }
    // Keep focus automation from fighting the viewer; clean up when it closes.
    try {
        viewerPopupRef.addEventListener("beforeunload", () => {
            viewerPopupRef = null;
            setSuppressAutoFocus(false);
            if (viewerPopupMonitor) {
                window.clearInterval(viewerPopupMonitor);
                viewerPopupMonitor = null;
            }
        });
    } catch (_) {
        /* ignore cross-window errors */
    }
    viewerPopupMonitor = window.setInterval(() => {
        if (!viewerPopupRef || viewerPopupRef.closed) {
            viewerPopupRef = null;
            setSuppressAutoFocus(false);
            window.clearInterval(viewerPopupMonitor);
            viewerPopupMonitor = null;
        }
    }, 800);
}

function focusSearchInput() {
    if (suppressAutoFocus || viewerIsOpen()) return;
    const input = document.getElementById("search-input");
    if (!input) return;
    if (document.activeElement === input) return;
    try {
        input.focus({ preventScroll: true });
        input.select();
    } catch (_) {
        /* ignore */
    }
}

function scheduleFocusSearchInput(delay = 30) {
    if (suppressAutoFocus || viewerIsOpen()) return;
    window.clearTimeout(scheduleFocusSearchInput._t);
    scheduleFocusSearchInput._t = window.setTimeout(() => focusSearchInput(), delay);
}

function normalizeSearchMode(value) {
    if (value === null || value === undefined) return null;
    const normalized = String(value).toLowerCase();
    return SEARCH_MODE_SET.has(normalized) ? normalized : null;
}

function readStoredSearchMode() {
    try {
        const stored = localStorage.getItem(SEARCH_MODE_KEY);
        return normalizeSearchMode(stored);
    } catch (_) {
        return null;
    }
}

function persistSearchMode(mode) {
    currentSearchMode = mode;
    try {
        localStorage.setItem(SEARCH_MODE_KEY, mode);
    } catch (_) {
        /* ignore */
    }
    const url = new URL(window.location.href);
    url.searchParams.set("mode", mode);
    history.replaceState(null, "", url.toString());
}

function updateSearchModeButtons(activeMode) {
    const buttons = document.querySelectorAll("#search-mode button");
    buttons.forEach((btn) => {
        const btnMode = btn.dataset.mode;
        const isActive = btnMode === activeMode;
        btn.classList.toggle("active", isActive);
        btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
}

function setupSearchModeSwitch() {
    const urlMode = normalizeSearchMode(new URL(window.location.href).searchParams.get("mode"));
    const storedMode = readStoredSearchMode();
    const fallback = DEFAULT_SEARCH_MODE;
    const initial = urlMode || storedMode || fallback;
    persistSearchMode(initial);
    updateSearchModeButtons(initial);
    const switcher = document.getElementById("search-mode");
    if (!switcher) return;
    switcher.querySelectorAll("button").forEach((btn) => {
        btn.addEventListener("click", () => {
            const next = normalizeSearchMode(btn.dataset.mode);
            if (!next || next === currentSearchMode) return;
            persistSearchMode(next);
            updateSearchModeButtons(next);
            search({ append: false });
            scheduleFocusSearchInput();
        });
    });
}

function normalizeTimeFilter(value) {
    if (value === null || value === undefined) return "";
    const v = String(value).toLowerCase();
    return TIME_FILTER_ORDER.includes(v) ? v : "";
}

function readStoredTimeFilter() {
    try {
        const raw = localStorage.getItem(TIME_FILTER_KEY);
        return normalizeTimeFilter(raw);
    } catch (_) {
        return "";
    }
}

function persistTimeFilter(value) {
    currentTimeFilter = normalizeTimeFilter(value);
    try {
        localStorage.setItem(TIME_FILTER_KEY, currentTimeFilter);
    } catch (_) {
        /* ignore */
    }
}

function labelForTime(value) {
    switch (value) {
        case "yesterday":
            return "Gestern";
        case "last7":
            return "7T";
        case "last30":
            return "30T";
        case "last365":
            return "365T";
        default:
            return value || "Alle";
    }
}

function longLabelForTime(value) {
    switch (value) {
        case "":
            return "Datum: alle";
        case "yesterday":
            return "Gestern";
        case "last7":
            return "Letzte 7 Tage";
        case "last30":
            return "Letzte 30 Tage";
        case "last365":
            return "Letzte 365 Tage";
        default:
            return `Jahr ${value}`;
    }
}

function buildTimeMoreMenu() {
    const menu = document.getElementById("time-more-menu");
    if (!menu) return;
    menu.innerHTML = "";
    TIME_MORE_OPTIONS.forEach((opt) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.dataset.time = opt;
        btn.setAttribute("role", "menuitemradio");
        btn.setAttribute("aria-checked", "false");
        btn.textContent = labelForTime(opt);
        menu.appendChild(btn);
    });
}

function buildFallbackTimeOptions(selectEl) {
    if (!selectEl) return;
    const options = [{ value: "", label: longLabelForTime("") }];
    TIME_PRIMARY_OPTIONS.filter((v) => v !== "").forEach((v) => options.push({ value: v, label: longLabelForTime(v) }));
    TIME_MORE_OPTIONS.forEach((v) => options.push({ value: v, label: longLabelForTime(v) }));
    selectEl.innerHTML = "";
    options.forEach(({ value, label }) => {
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = label;
        selectEl.appendChild(opt);
    });
}

function updateTimeChips(active) {
    document.querySelectorAll(".time-filter-chips .time-chip").forEach((btn) => {
        const isMore = btn.id === "time-more-button";
        const val = normalizeTimeFilter(btn.dataset.time);
        const isActive = isMore ? TIME_MORE_OPTIONS.includes(active) : val === active;
        btn.classList.toggle("active", isActive);
        btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
    const moreMenu = document.getElementById("time-more-menu");
    if (moreMenu) {
        moreMenu.querySelectorAll("button").forEach((btn) => {
            const val = normalizeTimeFilter(btn.dataset.time);
            const isActive = val === active;
            btn.classList.toggle("active", isActive);
            btn.setAttribute("aria-checked", isActive ? "true" : "false");
        });
    }
}

function closeTimeMoreMenu() {
    const menu = document.getElementById("time-more-menu");
    const btn = document.getElementById("time-more-button");
    if (menu && !menu.classList.contains("hidden")) {
        menu.classList.add("hidden");
        if (btn) btn.setAttribute("aria-expanded", "false");
    }
}

function toggleTimeMoreMenu() {
    const menu = document.getElementById("time-more-menu");
    const btn = document.getElementById("time-more-button");
    if (!menu || !btn) return;
    const nextVisible = menu.classList.contains("hidden");
    menu.classList.toggle("hidden", !nextVisible);
    btn.setAttribute("aria-expanded", nextVisible ? "true" : "false");
    if (nextVisible) {
        const active = menu.querySelector("button.active") || menu.querySelector("button");
        if (active) active.focus();
    }
}

function setupTimeFilterChips() {
    const stored = readStoredTimeFilter();
    const initial = normalizeTimeFilter(stored) || "";
    currentTimeFilter = initial;
    buildTimeMoreMenu();
    updateTimeChips(initial);
    const fallbackSelect = document.getElementById("time-filter");
    if (fallbackSelect) {
        buildFallbackTimeOptions(fallbackSelect);
        fallbackSelect.value = initial;
        fallbackSelect.addEventListener("change", () => {
            const next = normalizeTimeFilter(fallbackSelect.value);
            persistTimeFilter(next);
            updateTimeChips(next);
            search({ append: false });
            scheduleFocusSearchInput();
        });
    }
    const container = document.getElementById("time-filter-chips");
    if (!container) return;
    container.querySelectorAll(".time-chip").forEach((btn) => {
        if (btn.id === "time-more-button") return;
        btn.addEventListener("click", () => {
            const val = normalizeTimeFilter(btn.dataset.time);
            const next = val === currentTimeFilter ? "" : val;
            persistTimeFilter(next);
            updateTimeChips(next);
            if (fallbackSelect) fallbackSelect.value = next;
            closeTimeMoreMenu();
            search({ append: false });
            scheduleFocusSearchInput();
        });
    });
    const moreBtn = document.getElementById("time-more-button");
    const moreMenu = document.getElementById("time-more-menu");
    if (moreBtn && moreMenu) {
        moreBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            toggleTimeMoreMenu();
        });
        moreMenu.querySelectorAll("button").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                const val = normalizeTimeFilter(btn.dataset.time);
                persistTimeFilter(val);
                updateTimeChips(val);
                if (fallbackSelect) fallbackSelect.value = val;
                closeTimeMoreMenu();
                search({ append: false });
                scheduleFocusSearchInput();
            });
        });
        document.addEventListener("click", (e) => {
            if (!moreMenu.contains(e.target) && e.target !== moreBtn) {
                closeTimeMoreMenu();
            }
        });
        moreMenu.addEventListener("keydown", (e) => {
            const items = Array.from(moreMenu.querySelectorAll("button"));
            const idx = items.indexOf(document.activeElement);
            if (e.key === "Escape") {
                closeTimeMoreMenu();
                moreBtn.focus();
            }
            if (e.key === "ArrowRight" || e.key === "ArrowDown") {
                e.preventDefault();
                const next = items[(idx + 1) % items.length];
                next.focus();
            }
            if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
                e.preventDefault();
                const prev = items[(idx - 1 + items.length) % items.length];
                prev.focus();
            }
        });
    }
}
function normalizeTypeFilter(value) {
    if (value === null || value === undefined) return "";
    const normalized = String(value).toLowerCase();
    return TYPE_FILTER_SET.has(normalized) ? normalized : "";
}

function readStoredTypeFilter() {
    try {
        const stored = localStorage.getItem(TYPE_FILTER_KEY);
        return normalizeTypeFilter(stored);
    } catch (_) {
        return "";
    }
}

function persistTypeFilter(ext) {
    currentTypeFilter = ext;
    try {
        localStorage.setItem(TYPE_FILTER_KEY, ext);
    } catch (_) {
        /* ignore */
    }
}

function updateTypeFilterButtons(activeExt) {
    document.querySelectorAll("#type-filter button").forEach((btn) => {
        const val = normalizeTypeFilter(btn.dataset.ext);
        const isActive = val === activeExt;
        btn.classList.toggle("active", isActive);
        btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
}

function setupTypeFilterSwitch() {
    const stored = readStoredTypeFilter();
    const initial = normalizeTypeFilter(stored) || "";
    currentTypeFilter = initial;
    updateTypeFilterButtons(initial);
    const container = document.getElementById("type-filter");
    if (!container) return;
    container.querySelectorAll("button").forEach((btn) => {
        btn.addEventListener("click", () => {
            const next = normalizeTypeFilter(btn.dataset.ext);
            if (next === currentTypeFilter) return;
            persistTypeFilter(next);
            updateTypeFilterButtons(next);
            search({ append: false });
            scheduleFocusSearchInput();
        });
    });
}

applySavedPreviewWidth();
bootstrapZoom();

async function search({ append = false } = {}) {
    const q = document.getElementById("search-input").value || "";
    const trimmed = q.trim();
    const ext = normalizeTypeFilter(currentTypeFilter);
    const time = normalizeTimeFilter(currentTimeFilter);

    if (!append) {
        searchOffset = 0;
        searchHasMore = false;
    }

    if (!trimmed) {
        if (currentSearchController) {
            currentSearchController.abort();
            currentSearchController = null;
        }
        searchHasMore = false;
        renderMessageRow("Bitte einen Suchbegriff eingeben.");
        updateLoadMoreButton();
        return;
    }

    if (trimmed && trimmed !== "*" && trimmed.length < MIN_QUERY_LENGTH) {
        searchHasMore = false;
        renderMessageRow(`Mindestens ${MIN_QUERY_LENGTH} Zeichen eingeben.`);
        updateLoadMoreButton();
        return;
    }

    if (trimmed === "*" && !ext && !time) {
        if (currentSearchController) {
            currentSearchController.abort();
            currentSearchController = null;
        }
        searchHasMore = false;
        renderMessageRow("Wildcard nur mit aktivem Filter nutzen.");
        updateLoadMoreButton();
        return;
    }

    if (currentSearchController) {
        currentSearchController.abort();
    }
    currentSearchController = new AbortController();

    const activeMode = normalizeSearchMode(currentSearchMode) || DEFAULT_SEARCH_MODE;
    const params = new URLSearchParams({ q, limit: SEARCH_LIMIT, offset: append ? searchOffset : 0 });
    if (ext) params.append("extension", ext.toLowerCase());
    if (time) params.append("time_filter", time);
    if (sortState.key) {
        params.append("sort_key", sortState.key);
        params.append("sort_dir", sortState.dir);
    }
    params.append("mode", activeMode);

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
            scheduleFocusSearchInput();
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

function sanitizeFeedbackHtml(html) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(html || "", "text/html");
    doc.querySelectorAll("script, style").forEach((el) => el.remove());
    doc.body.querySelectorAll("*").forEach((el) => {
        const tag = el.tagName.toUpperCase();
        if (!FEEDBACK_ALLOWED_TAGS.has(tag)) {
            const parent = el.parentNode;
            if (parent) {
                while (el.firstChild) {
                    parent.insertBefore(el.firstChild, el);
                }
                parent.removeChild(el);
            }
            return;
        }
        Array.from(el.attributes).forEach((attr) => el.removeAttribute(attr.name));
    });
    return (doc.body.innerHTML || "").trim();
}

function updateFeedbackCounter() {
    if (!feedbackRefs.editor || !feedbackRefs.limit) return;
    const length = ((feedbackRefs.editor.textContent || "").trim().length) || 0;
    const label = `${Math.min(length, FEEDBACK_MAX_LEN)} / ${FEEDBACK_MAX_LEN}`;
    feedbackRefs.limit.textContent = label;
    feedbackRefs.limit.classList.toggle("over-limit", length > FEEDBACK_MAX_LEN);
}

function showFeedbackStatus(message, type = "info") {
    if (!feedbackRefs.status) return;
    feedbackRefs.status.textContent = message || "";
    feedbackRefs.status.className = "feedback-status";
    if (type === "success") feedbackRefs.status.classList.add("success");
    if (type === "error") feedbackRefs.status.classList.add("error");
    if (!message) {
        feedbackRefs.status.classList.add("hidden");
    } else {
        feedbackRefs.status.classList.remove("hidden");
    }
}

function resetFeedbackForm() {
    if (feedbackRefs.editor) {
        feedbackRefs.editor.innerHTML = "";
    }
    if (feedbackRefs.confirm) {
        feedbackRefs.confirm.classList.add("hidden");
    }
    showFeedbackStatus("");
    feedbackState.sending = false;
    updateFeedbackCounter();
}

function closeFeedbackPanel() {
    if (!feedbackRefs.overlay) return;
    feedbackRefs.overlay.classList.add("hidden");
    feedbackRefs.overlay.setAttribute("aria-hidden", "true");
    feedbackState.open = false;
    resetFeedbackForm();
}

function openFeedbackPanel() {
    if (!feedbackRefs.overlay || !feedbackRefs.editor) return;
    resetFeedbackForm();
    feedbackRefs.overlay.classList.remove("hidden");
    feedbackRefs.overlay.setAttribute("aria-hidden", "false");
    feedbackState.open = true;
    feedbackRefs.editor.focus();
}

async function sendFeedback() {
    if (feedbackState.sending) return;
    if (!feedbackRefs.editor) return;
    const text = (feedbackRefs.editor.textContent || "").trim();
    if (!text) {
        showFeedbackStatus("Bitte Feedback eingeben.", "error");
        return;
    }
    if (text.length > FEEDBACK_MAX_LEN) {
        showFeedbackStatus(`Maximal ${FEEDBACK_MAX_LEN} Zeichen.`, "error");
        return;
    }
    const sanitizedHtml = sanitizeFeedbackHtml(feedbackRefs.editor.innerHTML || "").slice(0, FEEDBACK_MAX_LEN * 4);

    feedbackState.sending = true;
    if (feedbackRefs.send) feedbackRefs.send.disabled = true;
    if (feedbackRefs.confirm) feedbackRefs.confirm.classList.add("hidden");
    showFeedbackStatus("Sende Feedback …");
    try {
        const res = await fetch("/api/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message_html: sanitizedHtml,
                message_text: text,
            }),
        });
        if (!res.ok) {
            showFeedbackStatus("Senden fehlgeschlagen.", "error");
            return;
        }
        showFeedbackStatus("Feedback gesendet.", "success");
        setTimeout(() => {
            closeFeedbackPanel();
        }, 1100);
    } catch (err) {
        showFeedbackStatus("Senden fehlgeschlagen.", "error");
    } finally {
        feedbackState.sending = false;
        if (feedbackRefs.send) feedbackRefs.send.disabled = false;
    }
}

function initFeedback() {
    if (!FEEDBACK_ENABLED) return;
    const trigger = document.getElementById("feedback-trigger");
    const overlay = document.getElementById("feedback-overlay");
    const editor = document.getElementById("feedback-editor");
    const limit = document.getElementById("feedback-limit");
    const status = document.getElementById("feedback-status");
    const sendBtn = document.getElementById("feedback-send");
    const cancelBtn = document.getElementById("feedback-cancel");
    const closeBtn = document.getElementById("feedback-close");
    const confirm = document.getElementById("feedback-confirm");
    const confirmYes = document.getElementById("feedback-confirm-yes");
    const confirmNo = document.getElementById("feedback-confirm-no");
    const subject = document.getElementById("feedback-subject");
    const toolbar = document.querySelectorAll(".feedback-toolbar button[data-cmd]");
    if (!trigger || !overlay || !editor || !sendBtn || !cancelBtn || !closeBtn || !confirm || !confirmYes || !confirmNo) return;
    feedbackRefs = {
        trigger,
        overlay,
        editor,
        limit,
        status,
        send: sendBtn,
        cancel: cancelBtn,
        close: closeBtn,
        confirm,
        confirmYes,
        confirmNo,
        subject,
    };
    if (subject) {
        subject.textContent = FEEDBACK_SUBJECT;
    }
    updateFeedbackCounter();
    trigger.addEventListener("click", () => openFeedbackPanel());
    closeBtn.addEventListener("click", () => closeFeedbackPanel());
    cancelBtn.addEventListener("click", () => closeFeedbackPanel());
    overlay.addEventListener("mousedown", (e) => {
        if (e.target === overlay) {
            closeFeedbackPanel();
        }
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && feedbackState.open) {
            closeFeedbackPanel();
        }
    });
    sendBtn.addEventListener("click", () => {
        confirm.classList.remove("hidden");
    });
    confirmYes.addEventListener("click", () => sendFeedback());
    confirmNo.addEventListener("click", () => confirm.classList.add("hidden"));
    editor.addEventListener("input", () => updateFeedbackCounter());
    toolbar.forEach((btn) => {
        btn.addEventListener("click", () => {
            const cmd = btn.dataset.cmd;
            if (!cmd) return;
            editor.focus();
            try {
                document.execCommand(cmd, false, null);
            } catch (err) {
                /* ignore */
            }
            updateFeedbackCounter();
        });
    });
}

function openPopupForRow(id) {
    if (!id) return;
    const url = `/viewer?id=${id}`;
    const w = Math.max(520, Math.floor(window.screen.availWidth * 0.45));
    const h = Math.max(480, Math.floor(window.screen.availHeight * 0.58));
    const left = Math.floor((window.screen.availWidth - w) / 2);
    const top = Math.floor((window.screen.availHeight - h) / 2);
    const win = window.open(
        url,
        "_blank",
        `width=${w},height=${h},left=${left},top=${top},resizable=yes,scrollbars=yes,toolbar=no,location=no,menubar=no`
    );
    if (win) {
        trackViewerPopup(win);
        try {
            win.focus();
        } catch (_) {
            /* ignore */
        }
    } else {
        setSuppressAutoFocus(false);
    }
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
setupSearchModeSwitch();
setupTypeFilterSwitch();
setupTimeFilterChips();
document.getElementById("search-input").addEventListener("input", debounceSearch);
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
focusSearchInput();
initFeedback();

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

    window.addEventListener("storage", (e) => {
        if (e.key === APP_ZOOM_KEY) {
            applyZoom(readSavedZoom(), { persist: false });
        }
    });
}

function bootstrapZoom() {
    applyZoom(readSavedZoom(), { persist: false });
}
