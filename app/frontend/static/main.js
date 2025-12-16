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
const SEARCH_MODE_KEY = "searchMode";
const SEARCH_MODE_SET = new Set(["strict", "standard", "loose"]);
const DEFAULT_SEARCH_MODE = normalizeSearchMode(window.searchDefaultMode) || "standard";
const TYPE_FILTER_KEY = "searchTypeFilter";
const TYPE_FILTER_SET = new Set(["", ".pdf", ".rtf", ".msg", ".txt"]);
const TIME_FILTER_KEY = "searchTimeFilter";
const SOURCE_FILTER_KEY = "searchSourceFilter";
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
let availableSources = [];
let activeSourceLabels = new Set();
let adminState = { admin: false, fileOpsEnabled: false, readySources: [] };
let adminReadySources = new Set();
let pendingDeleteId = null;
let pendingRename = null;
const dateFormatter = new Intl.DateTimeFormat("de-DE", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
});
let closeFeedbackOverlay = () => {};

function escapeHtml(str) {
    return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function fileExtension(name) {
    const trimmed = String(name || "").trim();
    const idx = trimmed.lastIndexOf(".");
    if (idx <= 0) return "";
    return trimmed.slice(idx).toLowerCase();
}

function focusSearchInput() {
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

function readStoredSourceFilter() {
    try {
        const raw = localStorage.getItem(SOURCE_FILTER_KEY);
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
            return new Set(parsed.map((v) => String(v)));
        }
    } catch (_) {
        /* ignore */
    }
    return new Set();
}

function persistSourceFilter() {
    try {
        localStorage.setItem(SOURCE_FILTER_KEY, JSON.stringify(Array.from(activeSourceLabels)));
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

function normalizeSourceList(list) {
    return Array.from(
        new Set(
            (list || [])
                .map((v) => (v === null || v === undefined ? "" : String(v).trim()))
                .filter(Boolean)
        )
    ).sort((a, b) => a.localeCompare(b, "de"));
}

async function loadSourceLabels() {
    try {
        const res = await fetch("/api/sources");
        if (!res.ok) return [];
        const data = await res.json();
        return normalizeSourceList(data.labels || []);
    } catch (_) {
        return [];
    }
}

function renderSourceFilter() {
    const container = document.getElementById("source-filter");
    if (!container) return;
    container.innerHTML = "";
    if (!availableSources.length) {
        return;
    }
    availableSources.forEach((label) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "source-chip time-chip";
        btn.textContent = label;
        btn.dataset.label = label;
        const active = activeSourceLabels.has(label);
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
        btn.addEventListener("click", () => {
            if (activeSourceLabels.has(label)) {
                activeSourceLabels.delete(label);
            } else {
                activeSourceLabels.add(label);
            }
            persistSourceFilter();
            renderSourceFilter();
            search({ append: false });
            scheduleFocusSearchInput();
        });
        container.appendChild(btn);
    });
}

async function setupSourceFilter() {
    const container = document.getElementById("source-filter");
    if (!container) return;
    activeSourceLabels = readStoredSourceFilter();
    availableSources = await loadSourceLabels();
    activeSourceLabels = new Set([...activeSourceLabels].filter((lbl) => availableSources.includes(lbl)));
    persistSourceFilter();
    renderSourceFilter();
}

function renderAdminUi() {
    const btn = document.getElementById("admin-button");
    const statusLabel = document.getElementById("admin-status-label");
    const readyListEl = document.getElementById("admin-ready-list");
    const available = adminState.fileOpsEnabled && adminReadySources.size > 0;
    const showButton = available || adminState.admin;
    if (btn) {
        btn.classList.toggle("hidden", !showButton);
        btn.classList.toggle("active", adminState.admin);
        btn.title = available ? "Admin" : "Admin-Funktionen nicht verfügbar";
    }
    if (statusLabel) {
        statusLabel.textContent = adminState.admin ? "Admin-Modus aktiv" : "Admin-Modus aus";
    }
    if (readyListEl) {
        if (!available) {
            readyListEl.textContent = "Keine Quelle bereit";
        } else {
            readyListEl.textContent = Array.from(adminReadySources).join(", ");
        }
    }
}

function updateAdminState(data) {
    adminState.admin = Boolean(data && data.admin);
    adminState.fileOpsEnabled = Boolean(data && data.file_ops_enabled);
    const readyList = Array.isArray(data && data.quarantine_ready_sources) ? data.quarantine_ready_sources : [];
    adminState.readySources = readyList;
    adminReadySources = new Set(readyList.map((item) => String(item.label || item)));
    renderAdminUi();
}

function canUseFileOpsForSource(label) {
    return Boolean(adminState.admin && adminState.fileOpsEnabled && adminReadySources.has(label));
}

async function refreshAdminStatus() {
    try {
        const res = await fetch("/api/admin/status");
        if (!res.ok) return;
        const data = await res.json();
        updateAdminState(data);
    } catch (_) {
        /* ignore */
    }
}

function setupAdminControls() {
    renderAdminUi();
    const btn = document.getElementById("admin-button");
    const modal = document.getElementById("admin-modal");
    const closeBtn = document.getElementById("admin-close");
    const loginBtn = document.getElementById("admin-login");
    const logoutBtn = document.getElementById("admin-logout");
    const input = document.getElementById("admin-password");
    const statusEl = document.getElementById("admin-modal-status");
    if (!btn || !modal || !loginBtn || !logoutBtn || !input || !statusEl) return;

    function setStatus(kind, text) {
        statusEl.classList.remove("error", "success", "hidden");
        if (!text) {
            statusEl.classList.add("hidden");
            statusEl.textContent = "";
            return;
        }
        statusEl.classList.add(kind === "error" ? "error" : "success");
        statusEl.textContent = text;
    }

    function openModal() {
        renderAdminUi();
        modal.classList.remove("hidden");
        setStatus("", "");
        input.value = "";
        input.focus();
    }

    function closeModal() {
        modal.classList.add("hidden");
        setStatus("", "");
        input.value = "";
    }

    async function submitLogin() {
        const password = input.value || "";
        setStatus("", "");
        try {
            const res = await fetch("/api/admin/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password }),
            });
            if (!res.ok) {
                let detail = "Login fehlgeschlagen.";
                try {
                    const data = await res.json();
                    detail = data.detail || detail;
                } catch (_) {
                    /* ignore */
                }
                setStatus("error", detail);
                return;
            }
            const data = await res.json();
            updateAdminState({ ...data, admin: true });
            setStatus("success", "Admin-Modus aktiviert.");
            setTimeout(() => closeModal(), 400);
        } catch (_) {
            setStatus("error", "Login fehlgeschlagen.");
        }
    }

    async function submitLogout() {
        setStatus("", "");
        try {
            await fetch("/api/admin/logout", { method: "POST" });
        } catch (_) {
            /* ignore */
        }
        updateAdminState({ admin: false, file_ops_enabled: adminState.fileOpsEnabled, quarantine_ready_sources: adminState.readySources });
        closeModal();
    }

    btn.addEventListener("click", () => {
        if (btn.classList.contains("hidden")) return;
        openModal();
    });
    loginBtn.addEventListener("click", submitLogin);
    logoutBtn.addEventListener("click", submitLogout);
    closeBtn?.addEventListener("click", closeModal);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            submitLogin();
        }
    });
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
    const sources = Array.from(activeSourceLabels || []);

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

    if (trimmed === "*" && !ext && !time && !sources.length) {
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
    if (sources.length) {
        sources.forEach((label) => params.append("source_labels", label));
    }
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
        tr.dataset.source = row.source || "";
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
setupSearchModeSwitch();
setupTypeFilterSwitch();
setupTimeFilterChips();
setupSourceFilter();
setupAdminControls();
setupDeleteConfirm();
setupRenameDialog();
refreshAdminStatus();
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

function removeResultRow(id) {
    const row = document.querySelector(`#results-table tbody tr[data-id="${id}"]`);
    if (row) {
        row.remove();
    }
    if (currentDocId && String(currentDocId) === String(id)) {
        closePreviewPanel();
    }
    const tbody = document.querySelector("#results-table tbody");
    if (tbody && !tbody.children.length) {
        renderMessageRow("Keine Treffer gefunden.");
    }
}

function closeDeleteConfirm() {
    const modal = document.getElementById("delete-confirm");
    const errorEl = document.getElementById("delete-error");
    const confirmBtn = document.getElementById("delete-confirm-btn");
    pendingDeleteId = null;
    if (modal) {
        modal.classList.add("hidden");
        modal.dataset.source = "";
    }
    if (errorEl) {
        errorEl.textContent = "";
        errorEl.classList.add("hidden");
    }
    if (confirmBtn) {
        confirmBtn.disabled = false;
    }
}

function showDeleteConfirm(docId, filename, sourceLabel) {
    const modal = document.getElementById("delete-confirm");
    const nameEl = document.getElementById("delete-filename");
    const errorEl = document.getElementById("delete-error");
    const confirmBtn = document.getElementById("delete-confirm-btn");
    if (!modal || !nameEl || !confirmBtn || !errorEl) return;
    pendingDeleteId = docId;
    modal.dataset.source = sourceLabel || "";
    nameEl.textContent = filename || "Datei";
    errorEl.textContent = "";
    errorEl.classList.add("hidden");
    confirmBtn.disabled = false;
    modal.classList.remove("hidden");
}

async function performDelete() {
    const modal = document.getElementById("delete-confirm");
    const errorEl = document.getElementById("delete-error");
    const confirmBtn = document.getElementById("delete-confirm-btn");
    const sourceLabel = modal?.dataset.source || "";
    if (!pendingDeleteId || !modal) return;
    if (!canUseFileOpsForSource(sourceLabel)) {
        if (errorEl) {
            errorEl.textContent = "Aktion nicht erlaubt.";
            errorEl.classList.remove("hidden");
        }
        return;
    }
    if (confirmBtn) confirmBtn.disabled = true;
    try {
        const res = await fetch(`/api/files/${pendingDeleteId}/quarantine-delete`, { method: "POST" });
        if (!res.ok) {
            let detail = "Verschieben fehlgeschlagen.";
            try {
                const data = await res.json();
                detail = data.detail || detail;
            } catch (_) {
                /* ignore */
            }
            if (res.status === 401 || res.status === 403) {
                updateAdminState({ admin: false, file_ops_enabled: adminState.fileOpsEnabled, quarantine_ready_sources: adminState.readySources });
            }
            if (errorEl) {
                errorEl.textContent = detail;
                errorEl.classList.remove("hidden");
            }
            if (confirmBtn) confirmBtn.disabled = false;
            return;
        }
        removeResultRow(pendingDeleteId);
        closeDeleteConfirm();
    } catch (_) {
        if (errorEl) {
            errorEl.textContent = "Verschieben fehlgeschlagen.";
            errorEl.classList.remove("hidden");
        }
        if (confirmBtn) confirmBtn.disabled = false;
    }
}

function setupDeleteConfirm() {
    const modal = document.getElementById("delete-confirm");
    if (!modal) return;
    const confirmBtn = document.getElementById("delete-confirm-btn");
    const cancelBtn = document.getElementById("delete-cancel");
    const closeBtn = document.getElementById("delete-close");
    confirmBtn?.addEventListener("click", performDelete);
    cancelBtn?.addEventListener("click", closeDeleteConfirm);
    closeBtn?.addEventListener("click", closeDeleteConfirm);
    modal.addEventListener("click", (e) => {
        if (e.target === modal) {
            closeDeleteConfirm();
        }
    });
}

function closeRenameDialog() {
    const modal = document.getElementById("rename-dialog");
    const errorEl = document.getElementById("rename-error");
    const input = document.getElementById("rename-input");
    const confirmBtn = document.getElementById("rename-confirm");
    pendingRename = null;
    if (modal) modal.classList.add("hidden");
    if (errorEl) {
        errorEl.textContent = "";
        errorEl.classList.add("hidden");
    }
    if (input) {
        input.value = "";
    }
    if (confirmBtn) confirmBtn.disabled = true;
}

function validateRenameInput(value, originalName) {
    const cleaned = (value || "").trim();
    if (!cleaned) return "Name erforderlich";
    if (cleaned === originalName) return "Name unverändert";
    if (cleaned === "." || cleaned === "..") return "Ungültiger Name";
    if (/[\\\\/]/.test(cleaned) || cleaned.includes("\u0000")) return "Ungültiger Name";
    if (fileExtension(cleaned) !== fileExtension(originalName)) return "Dateiendung unverändert lassen";
    return "";
}

function updateRenameValidation() {
    const input = document.getElementById("rename-input");
    const errorEl = document.getElementById("rename-error");
    const confirmBtn = document.getElementById("rename-confirm");
    if (!pendingRename || !input || !errorEl || !confirmBtn) return;
    const err = validateRenameInput(input.value, pendingRename.name);
    if (err) {
        errorEl.textContent = err;
        errorEl.classList.remove("hidden");
        confirmBtn.disabled = true;
    } else {
        errorEl.textContent = "";
        errorEl.classList.add("hidden");
        confirmBtn.disabled = false;
    }
}

function showRenameDialog(docId) {
    const modal = document.getElementById("rename-dialog");
    const currentEl = document.getElementById("rename-current-name");
    const input = document.getElementById("rename-input");
    const errorEl = document.getElementById("rename-error");
    const confirmBtn = document.getElementById("rename-confirm");
    if (!modal || !currentEl || !input || !errorEl || !confirmBtn) return;
    const row = document.querySelector(`#results-table tbody tr[data-id="${docId}"]`);
    const sourceLabel = row?.dataset.source || "";
    if (!canUseFileOpsForSource(sourceLabel)) {
        closeContextMenu();
        return;
    }
    const name = row?.querySelector(".filename")?.textContent?.trim() || "";
    const pathLabel = row?.querySelector(".path-cell")?.textContent?.trim() || "";
    pendingRename = { id: docId, source: sourceLabel, name, path: pathLabel };
    currentEl.textContent = name || "Datei";
    input.value = name || "";
    errorEl.textContent = "";
    errorEl.classList.add("hidden");
    confirmBtn.disabled = true;
    modal.classList.remove("hidden");
    input.focus();
    input.select();
}

function applyRenameResult(data) {
    const id = data?.doc_id || (pendingRename && pendingRename.id);
    if (!id) return;
    const newPath = data?.display_path || data?.new_path || (pendingRename ? pendingRename.path : "");
    const newName = data?.display_name || (newPath ? newPath.split("/").pop() : pendingRename?.name || "");
    const row = document.querySelector(`#results-table tbody tr[data-id="${id}"]`);
    if (row) {
        const nameEl = row.querySelector(".filename");
        const pathEl = row.querySelector(".path-cell");
        if (nameEl && newName) {
            nameEl.textContent = newName;
            nameEl.title = newName;
        }
        if (pathEl && newPath) {
            pathEl.textContent = newPath;
            pathEl.title = newPath;
        }
    }
    if (currentDocId && String(currentDocId) === String(id)) {
        const nameHeader = document.getElementById("preview-name");
        const pathHeader = document.getElementById("preview-path");
        if (nameHeader && newName) nameHeader.textContent = newName;
        if (pathHeader && newPath) pathHeader.textContent = newPath;
    }
}

async function performRename() {
    const modal = document.getElementById("rename-dialog");
    const input = document.getElementById("rename-input");
    const errorEl = document.getElementById("rename-error");
    const confirmBtn = document.getElementById("rename-confirm");
    if (!pendingRename || !modal || !input || !errorEl || !confirmBtn) return;
    const validationError = validateRenameInput(input.value, pendingRename.name);
    if (validationError) {
        errorEl.textContent = validationError;
        errorEl.classList.remove("hidden");
        confirmBtn.disabled = true;
        return;
    }
    if (!canUseFileOpsForSource(pendingRename.source)) {
        errorEl.textContent = "Aktion nicht erlaubt.";
        errorEl.classList.remove("hidden");
        confirmBtn.disabled = true;
        return;
    }
    confirmBtn.disabled = true;
    try {
        const res = await fetch(`/api/files/${pendingRename.id}/rename`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ new_name: (input.value || "").trim() }),
        });
        if (!res.ok) {
            let detail = "Umbenennen fehlgeschlagen.";
            try {
                const data = await res.json();
                detail = data.detail || detail;
            } catch (_) {
                /* ignore */
            }
            if (res.status === 401 || res.status === 403) {
                updateAdminState({ admin: false, file_ops_enabled: adminState.fileOpsEnabled, quarantine_ready_sources: adminState.readySources });
            }
            errorEl.textContent = detail;
            errorEl.classList.remove("hidden");
            confirmBtn.disabled = false;
            return;
        }
        const data = await res.json();
        applyRenameResult(data);
        closeRenameDialog();
    } catch (_) {
        errorEl.textContent = "Umbenennen fehlgeschlagen.";
        errorEl.classList.remove("hidden");
        confirmBtn.disabled = false;
    }
}

function setupRenameDialog() {
    const modal = document.getElementById("rename-dialog");
    if (!modal) return;
    const confirmBtn = document.getElementById("rename-confirm");
    const cancelBtn = document.getElementById("rename-cancel");
    const input = document.getElementById("rename-input");
    confirmBtn?.addEventListener("click", performRename);
    cancelBtn?.addEventListener("click", closeRenameDialog);
    modal.addEventListener("click", (e) => {
        if (e.target === modal) closeRenameDialog();
    });
    input?.addEventListener("input", updateRenameValidation);
    input?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            if (!document.getElementById("rename-confirm")?.disabled) {
                performRename();
            }
        }
    });
}

function handleDeleteAction(id) {
    const row = document.querySelector(`#results-table tbody tr[data-id="${id}"]`);
    const sourceLabel = row?.dataset.source || "";
    if (!canUseFileOpsForSource(sourceLabel)) {
        closeContextMenu();
        return;
    }
    const name = row?.querySelector(".filename")?.textContent?.trim() || "Datei";
    closeContextMenu();
    showDeleteConfirm(id, name, sourceLabel);
}

function handleRenameAction(id) {
    const row = document.querySelector(`#results-table tbody tr[data-id="${id}"]`);
    const sourceLabel = row?.dataset.source || "";
    if (!canUseFileOpsForSource(sourceLabel)) {
        closeContextMenu();
        return;
    }
    closeContextMenu();
    showRenameDialog(id);
}

// Context menu
let contextMenuEl = null;
function showContextMenu(e, id) {
    e.preventDefault();
    closeContextMenu();
    const menu = document.createElement("div");
    menu.className = "context-menu";
    const ul = document.createElement("ul");
    const row = document.querySelector(`#results-table tbody tr[data-id="${id}"]`);
    const sourceLabel = row?.dataset.source || "";
    const items = [
        { action: "preview", label: "Preview" },
        { action: "popup", label: "Pop-up" },
        { action: "download", label: "Download" },
        { action: "print", label: "Drucken" },
    ];
    if (canUseFileOpsForSource(sourceLabel)) {
        items.push({ action: "rename", label: "Umbenennen\u2026" });
        items.push({ action: "delete", label: "Löschen", danger: true });
    }
    items.forEach((item) => {
        const li = document.createElement("li");
        li.dataset.action = item.action;
        li.textContent = item.label;
        if (item.danger) {
            li.classList.add("danger");
        }
        ul.appendChild(li);
    });
    ul.addEventListener("click", (ev) => {
        const action = ev.target.dataset.action;
        if (action === "preview") openPreview(id, true);
        if (action === "popup") openPopupForRow(id);
        if (action === "download") window.open(`/api/document/${id}/file?download=1`, "_blank");
        if (action === "print") printDocument(id);
        if (action === "delete") {
            handleDeleteAction(id);
            return;
        }
        if (action === "rename") {
            handleRenameAction(id);
            return;
        }
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
    if (e.target.closest("#admin-modal")) return;
    if (e.target.closest("#delete-confirm")) return;
    closePreviewPanel();
});

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        closePreviewPanel();
        closeContextMenu();
        closeFeedbackOverlay();
        closeDeleteConfirm();
        const adminModal = document.getElementById("admin-modal");
        if (adminModal && !adminModal.classList.contains("hidden")) {
            adminModal.classList.add("hidden");
        }
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

// Feedback overlay
const MAX_FEEDBACK_LEN = 5000;

function setupFeedback() {
    const enabled = window.feedbackEnabled === true || String(window.feedbackEnabled || "").toLowerCase() === "true";
    if (!enabled) return;
    const overlay = document.getElementById("feedback-overlay");
    const trigger = document.getElementById("feedback-trigger");
    const editor = document.getElementById("feedback-editor");
    const limitEl = document.getElementById("feedback-limit");
    const closeBtn = document.getElementById("feedback-close");
    const cancelBtn = document.getElementById("feedback-cancel");
    const sendBtn = document.getElementById("feedback-send");
    const confirmWrap = document.getElementById("feedback-confirm");
    const confirmYes = document.getElementById("feedback-confirm-yes");
    const confirmNo = document.getElementById("feedback-confirm-no");
    const statusEl = document.getElementById("feedback-status");
    const toolbarBtns = document.querySelectorAll(".feedback-toolbar button[data-cmd]");
    if (!overlay || !trigger || !editor || !limitEl || !sendBtn || !confirmWrap || !statusEl) return;

    let sending = false;

    function readCookie(name) {
        const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
        return m ? decodeURIComponent(m[1]) : null;
    }

    function setStatus(kind, text) {
        if (!statusEl) return;
        statusEl.classList.remove("hidden", "success", "error");
        statusEl.classList.add(kind === "error" ? "error" : "success");
        statusEl.textContent = text || "";
    }

    function clearStatus() {
        if (!statusEl) return;
        statusEl.classList.add("hidden");
        statusEl.classList.remove("success", "error");
        statusEl.textContent = "";
    }

    function getPlainText() {
        return (editor.textContent || "").trim();
    }

    function updateLimit() {
        const len = getPlainText().length;
        limitEl.textContent = `${len} / ${MAX_FEEDBACK_LEN}`;
        const over = len > MAX_FEEDBACK_LEN;
        limitEl.classList.toggle("over-limit", over);
        sendBtn.disabled = sending || !len || over;
    }

    function placeCaretAtEnd(el) {
        try {
            const range = document.createRange();
            range.selectNodeContents(el);
            range.collapse(false);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        } catch (_) {
            /* ignore */
        }
    }

    function openOverlay() {
        overlay.classList.remove("hidden");
        overlay.setAttribute("aria-hidden", "false");
        confirmWrap.classList.add("hidden");
        clearStatus();
        updateLimit();
        editor.focus({ preventScroll: true });
        placeCaretAtEnd(editor);
        document.body.style.overflow = "hidden";
    }

    closeFeedbackOverlay = function closeFeedbackOverlay() {
        overlay.classList.add("hidden");
        overlay.setAttribute("aria-hidden", "true");
        confirmWrap.classList.add("hidden");
        clearStatus();
        sending = false;
        document.body.style.overflow = "";
    };

    function resetEditor() {
        editor.innerHTML = "";
        updateLimit();
    }

    function showConfirm(show) {
        confirmWrap.classList.toggle("hidden", !show);
    }

    function setSending(state) {
        sending = state;
        sendBtn.disabled = state || !getPlainText().length || getPlainText().length > MAX_FEEDBACK_LEN;
        confirmYes.disabled = state;
        confirmNo.disabled = state;
        sendBtn.textContent = state ? "Senden…" : "Senden";
    }

    async function submitFeedback() {
        const text = getPlainText();
        if (!text) {
            setStatus("error", "Bitte Feedback eingeben.");
            return;
        }
        if (text.length > MAX_FEEDBACK_LEN) {
            setStatus("error", `Maximal ${MAX_FEEDBACK_LEN} Zeichen.`);
            return;
        }
        setSending(true);
        clearStatus();
        showConfirm(false);
        const headers = { "Content-Type": "application/json" };
        const cookieSecret = readCookie("app_secret");
        if (cookieSecret) {
            headers["X-App-Secret"] = cookieSecret;
        }
        try {
            const res = await fetch("/api/feedback", {
                method: "POST",
                headers,
                body: JSON.stringify({
                    message_html: editor.innerHTML,
                    message_text: text,
                }),
            });
            if (!res.ok) {
                let detail = "";
                try {
                    const data = await res.json();
                    detail = data.detail || "";
                } catch (_) {
                    /* ignore */
                }
                const msg =
                    res.status === 401
                        ? "Nicht autorisiert."
                        : res.status === 429
                          ? "Zu viele Feedbacks. Bitte später erneut versuchen."
                          : detail || "Feedback konnte nicht gesendet werden.";
                setStatus("error", msg);
                return;
            }
            setStatus("success", "Feedback wurde gesendet. Vielen Dank!");
            resetEditor();
        } catch (err) {
            setStatus("error", "Verbindung fehlgeschlagen. Bitte erneut versuchen.");
        } finally {
            setSending(false);
        }
    }

    trigger.addEventListener("click", openOverlay);
    closeBtn?.addEventListener("click", closeFeedbackOverlay);
    cancelBtn?.addEventListener("click", closeFeedbackOverlay);
    overlay.addEventListener("click", (e) => {
        if (e.target === overlay) {
            closeFeedbackOverlay();
        }
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !overlay.classList.contains("hidden")) {
            closeFeedbackOverlay();
        }
    });

    toolbarBtns.forEach((btn) => {
        btn.addEventListener("click", () => {
            const cmd = btn.dataset.cmd;
            if (!cmd) return;
            editor.focus();
            try {
                document.execCommand(cmd, false, null);
            } catch (_) {
                /* ignore */
            }
            updateLimit();
        });
    });

    editor.addEventListener("input", updateLimit);
    editor.addEventListener("paste", (e) => {
        e.preventDefault();
        const text = (e.clipboardData || window.clipboardData).getData("text");
        try {
            document.execCommand("insertText", false, text);
        } catch (_) {
            editor.textContent += text;
        }
        updateLimit();
    });

    sendBtn.addEventListener("click", () => {
        clearStatus();
        if (getPlainText().length > MAX_FEEDBACK_LEN) {
            setStatus("error", `Maximal ${MAX_FEEDBACK_LEN} Zeichen.`);
            return;
        }
        if (!getPlainText().length) {
            setStatus("error", "Bitte Feedback eingeben.");
            return;
        }
        showConfirm(true);
    });

    confirmNo?.addEventListener("click", () => showConfirm(false));
    confirmYes?.addEventListener("click", submitFeedback);

    updateLimit();
}

setupFeedback();
