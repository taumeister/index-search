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
const ZEN_STEPS = [15, 30, 45, Infinity];
const DEFAULT_ZEN_STEP_IDX = 0;
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
const SEARCH_FAV_KEY = "searchFavorites";
const TIME_YEAR_MAX = 2025;
const TIME_YEAR_MIN = 2000;
const TIME_PRIMARY_OPTIONS = ["", "yesterday", "last7", "last30"];
const TIME_MORE_OPTIONS = ["last365", ...Array.from({ length: TIME_YEAR_MAX - TIME_YEAR_MIN + 1 }, (_, i) => String(TIME_YEAR_MAX - i))];
const TIME_FILTER_ORDER = [...TIME_PRIMARY_OPTIONS, ...TIME_MORE_OPTIONS];
let searchOffset = 0;
let searchHasMore = false;
let searchLoading = false;
let zenModeEnabled = false;
let zenStepIdx = DEFAULT_ZEN_STEP_IDX;
let zenToggleHome = null;
let zenToggleNextSibling = null;
let currentSearchMode = DEFAULT_SEARCH_MODE;
let currentTypeFilter = "";
let currentTimeFilter = "";
const METRICS_ENABLED = true;
let availableSources = [];
let activeSourceLabels = new Set();
let adminState = { admin: false, fileOpsEnabled: false, readySources: [] };
let adminReadySources = new Set();
let adminLoggedIn = false;
let adminAlwaysOn = Boolean(
    typeof window !== "undefined" &&
        (window.adminAlwaysOn === true || String(window.adminAlwaysOn || "").toLowerCase() === "true")
);
if (adminAlwaysOn) {
    adminLoggedIn = true;
}
if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-admin-always-on", adminAlwaysOn ? "true" : "false");
}
if (typeof window !== "undefined" && !window.openAdminModal) {
    window.openAdminModal = () => console.error("[admin] Admin-Overlay nicht initialisiert.");
}
const THEME_KEY = "theme";
const DEFAULT_THEME = "lumen-atelier";
const THEMES = [
    { id: "lumen-atelier", label: "Lumen Atelier", tone: "Light" },
    { id: "marble-coast", label: "Marble Coast", tone: "Light" },
    { id: "aurora-atelier", label: "Aurora Atelier", tone: "Light" },
    { id: "nocturne-atlas", label: "Nocturne Atlas", tone: "Dark" },
    { id: "graphite-ember", label: "Graphite Ember", tone: "Dark" },
    { id: "velvet-eclipse", label: "Velvet Eclipse", tone: "Dark" },
    { id: "obsidian-prism", label: "Obsidian Prism", tone: "Dark" },
];

function normalizeTheme(value) {
    if (!value) return null;
    const normalized = String(value).trim().toLowerCase();
    return THEMES.find((t) => t.id === normalized)?.id || null;
}

function themeLabel(themeId) {
    return THEMES.find((t) => t.id === themeId)?.label || themeId || "Theme";
}

function readStoredTheme() {
    try {
        const stored = localStorage.getItem(THEME_KEY);
        return normalizeTheme(stored);
    } catch (_) {
        return null;
    }
}

function applyTheme(themeId) {
    const next = normalizeTheme(themeId) || DEFAULT_THEME;
    document.documentElement.setAttribute("data-theme", next);
    return next;
}

function persistTheme(themeId) {
    const next = applyTheme(themeId);
    try {
        localStorage.setItem(THEME_KEY, next);
    } catch (_) {
        /* ignore */
    }
    const labelEl = document.getElementById("theme-toggle-label");
    if (labelEl) labelEl.textContent = themeLabel(next);
    renderThemeMenu(next);
}

function renderThemeMenu(activeTheme) {
    const menu = document.getElementById("theme-menu");
    if (!menu) return;
    menu.innerHTML = "";
    THEMES.forEach((theme) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.dataset.theme = theme.id;
        btn.className = theme.id === activeTheme ? "active" : "";
        btn.setAttribute("role", "menuitemradio");
        btn.setAttribute("aria-checked", theme.id === activeTheme ? "true" : "false");
        btn.innerHTML = `<span class="theme-name">${theme.label}</span><span class="theme-meta">${theme.tone}</span>`;
        btn.addEventListener("click", () => {
            if (theme.id === activeTheme) {
                closeThemeMenu();
                return;
            }
            persistTheme(theme.id);
            closeThemeMenu();
        });
        menu.appendChild(btn);
    });
}

function closeThemeMenu() {
    const menu = document.getElementById("theme-menu");
    const toggle = document.getElementById("theme-toggle");
    if (menu && !menu.classList.contains("hidden")) {
        menu.classList.add("hidden");
        toggle?.setAttribute("aria-expanded", "false");
    }
}

function toggleThemeMenu() {
    const menu = document.getElementById("theme-menu");
    const toggle = document.getElementById("theme-toggle");
    if (!menu || !toggle) return;
    const nextOpen = menu.classList.contains("hidden");
    menu.classList.toggle("hidden", !nextOpen);
    toggle.setAttribute("aria-expanded", nextOpen ? "true" : "false");
    if (nextOpen) {
        const active = menu.querySelector("button.active") || menu.querySelector("button");
        active?.focus();
    }
}

function setupThemeSwitcher() {
    const toggle = document.getElementById("theme-toggle");
    const menu = document.getElementById("theme-menu");
    if (!toggle || !menu) {
        const fallbackTheme = normalizeTheme(document.documentElement.getAttribute("data-theme")) || readStoredTheme() || DEFAULT_THEME;
        applyTheme(fallbackTheme);
        return;
    }
    const initialTheme = normalizeTheme(document.documentElement.getAttribute("data-theme")) || readStoredTheme() || DEFAULT_THEME;
    persistTheme(initialTheme);
    toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleThemeMenu();
    });
    document.addEventListener("click", (e) => {
        if (!menu.contains(e.target) && e.target !== toggle) {
            closeThemeMenu();
        }
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeThemeMenu();
            if (!menu.classList.contains("hidden")) {
                toggle.focus();
            }
        }
    });
    renderThemeMenu(initialTheme);
}
let pendingDeleteId = null;
let pendingRename = null;
let searchFavorites = [];
let favHoverTimer = null;
const dateFormatter = new Intl.DateTimeFormat("de-DE", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
});
let closeFeedbackOverlay = () => {};
let showToast = () => {};

function feedbackFeatureEnabled() {
    return window.feedbackEnabled === true || String(window.feedbackEnabled || "").toLowerCase() === "true";
}

function readSearchFavorites() {
    try {
        const raw = localStorage.getItem(SEARCH_FAV_KEY);
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
            return parsed.filter((item) => typeof item === "string").slice(0, 10);
        }
    } catch (_) {
        /* ignore */
    }
    return [];
}

function writeSearchFavorites(list) {
    try {
        localStorage.setItem(SEARCH_FAV_KEY, JSON.stringify(list.slice(0, 10)));
    } catch (_) {
        /* ignore */
    }
}
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

function setupSearchFavorites() {
    searchFavorites = readSearchFavorites();
    const searchWrap = document.querySelector(".search-input-wrap");
    const input = document.getElementById("search-input");
    if (!searchWrap || !input) return;
    const star = document.getElementById("search-fav");
    const dropdown = document.getElementById("fav-dropdown");
    if (!star || !dropdown) return;

    star.addEventListener("click", () => {
        const val = input.value.trim();
        if (val) {
            addSearchFavorite(val);
        }
        toggleFavDropdown();
    });

    input.addEventListener("click", () => openFavDropdown());
    input.addEventListener("input", () => closeFavDropdown());
    input.addEventListener("blur", () => {
        window.setTimeout(() => closeFavDropdown(), 120);
    });

    dropdown.addEventListener("click", (e) => {
        const removeBtn = e.target.closest(".fav-remove");
        if (removeBtn) {
            const idx = Number(removeBtn.dataset.idx);
            removeSearchFavorite(idx);
            e.stopPropagation();
            return;
        }
        const item = e.target.closest(".fav-item");
        if (item && item.dataset.value) {
            e.stopPropagation();
            input.value = item.dataset.value;
            closeFavDropdown();
            search({ append: false });
        }
    });

    document.addEventListener("click", (e) => {
        if (e.target.closest("#fav-dropdown") || e.target.closest("#search-fav") || e.target.closest("#search-input")) return;
        closeFavDropdown();
    });

    renderSearchFavorites();
}

function renderAdminUi() {
    const btn = document.getElementById("admin-button");
    const statusLabel = document.getElementById("admin-status-label");
    const readyListEl = document.getElementById("admin-ready-list");
    const available = adminState.fileOpsEnabled && adminReadySources.size > 0;
    const showButton = available || adminState.admin || adminAlwaysOn;
    if (btn) {
        btn.classList.toggle("hidden", !showButton);
        btn.classList.toggle("active", adminState.admin || adminAlwaysOn);
        btn.title = adminAlwaysOn
            ? "Admin dauerhaft aktiv"
            : available
              ? "Admin"
              : "Admin-Funktionen nicht verfügbar";
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
    const fromApi = data && typeof data.admin_always_on !== "undefined" ? data.admin_always_on : adminAlwaysOn;
    adminAlwaysOn = Boolean(fromApi);
    try {
        document.documentElement.setAttribute("data-admin-always-on", adminAlwaysOn ? "true" : "false");
    } catch (_) {
        /* ignore */
    }
    const adminFromApi = Boolean(data && data.admin);
    if (adminFromApi) {
        adminLoggedIn = true;
    }
    adminState.admin = Boolean(adminAlwaysOn || adminLoggedIn || adminFromApi);
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
    if (!btn || !modal || !loginBtn || !logoutBtn || !input || !statusEl) {
        console.error("[admin] Admin-UI fehlt oder ist unvollständig.", {
            button: !!btn,
            modal: !!modal,
            loginBtn: !!loginBtn,
            logoutBtn: !!logoutBtn,
            input: !!input,
            statusEl: !!statusEl,
        });
        window.openAdminModal = () => console.error("[admin] Admin-Overlay nicht initialisiert.");
        return;
    }
    function setAdminOverlayOpen(state) {
        document.documentElement.setAttribute("data-admin-open", state ? "true" : "false");
    }

    setAdminOverlayOpen(false);

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

async function forceLogout(reason = "reauth") {
    if (adminAlwaysOn) {
        return;
    }
    adminLoggedIn = false;
    updateAdminState({ admin: false, file_ops_enabled: adminState.fileOpsEnabled, quarantine_ready_sources: adminState.readySources });
    try {
        await fetch("/api/admin/logout", { method: "POST" });
    } catch (err) {
        console.error("[admin] Logout fehlgeschlagen (%s)", reason, err);
        }
        await refreshAdminStatus();
    }

    async function openModal(options = {}) {
        if (adminAlwaysOn) {
            setStatus("success", "Admin-Modus dauerhaft aktiv.");
            adminLoggedIn = true;
            updateAdminState({ admin: true, admin_always_on: true, file_ops_enabled: adminState.fileOpsEnabled, quarantine_ready_sources: adminState.readySources });
            renderAdminUi();
            modal.classList.remove("hidden");
            setAdminOverlayOpen(true);
            document.body.classList.add("dialog-open");
            document.body.style.overflow = "hidden";
            return;
        }
        const opts = typeof options === "object" && options !== null ? options : {};
        const forceReauth = opts.forceReauth !== false;
        setStatus("", "");
        if (forceReauth) {
            await forceLogout("force-open");
        }
        renderAdminUi();
        modal.classList.remove("hidden");
        input.value = "";
        setAdminOverlayOpen(true);
        document.body.classList.add("dialog-open");
        document.body.style.overflow = "hidden";
        try {
            input.focus({ preventScroll: true });
        } catch (_) {
            input.focus();
        }
    }

    function closeModal() {
        modal.classList.add("hidden");
        setStatus("", "");
        input.value = "";
        setAdminOverlayOpen(false);
        document.body.classList.remove("dialog-open");
        document.body.style.overflow = "";
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
                let detail = res.status === 401 ? "Ungültiges Passwort." : "Login fehlgeschlagen.";
                try {
                    const data = await res.json();
                    detail = data.detail || detail;
                    if (detail.toLowerCase() === "unauthorized") {
                        detail = "Login fehlgeschlagen.";
                    }
                } catch (_) {
                    /* ignore */
                }
                setStatus("error", detail || "Falsches Passwort oder keine Berechtigung.");
                return;
            }
            const data = await res.json();
            adminLoggedIn = true;
            updateAdminState({ ...data, admin: true });
            setStatus("success", "Admin-Modus aktiviert.");
            setTimeout(() => closeModal(), 400);
        } catch (err) {
            console.error("[admin] Login-Request fehlgeschlagen.", err);
            setStatus("error", "Login fehlgeschlagen.");
        }
    }

    async function submitLogout() {
        if (adminAlwaysOn) {
            closeModal();
            renderAdminUi();
            return;
        }
        setStatus("", "");
        adminLoggedIn = false;
        await forceLogout("manual");
        closeModal();
    }

    btn.addEventListener("click", () => {
        openModal({ forceReauth: true });
    });
    window.openAdminModal = openModal;
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
        if (zenModeEnabled) {
            resetZenLimit();
            applyZenVisibility();
        }
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
        updateLoadMoreButton();
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

function getZenVisibleLimit() {
    if (!zenModeEnabled) return Infinity;
    const step = ZEN_STEPS[zenStepIdx] ?? Infinity;
    return step;
}

function resetZenLimit() {
    zenStepIdx = DEFAULT_ZEN_STEP_IDX;
}

function advanceZenStep(totalRows) {
    if (!zenModeEnabled) return;
    const maxIdx = ZEN_STEPS.length - 1;
    if (zenStepIdx >= maxIdx) return;
    const limit = getZenVisibleLimit();
    if (Number.isFinite(limit) && totalRows <= limit) return;
    zenStepIdx = Math.min(maxIdx, zenStepIdx + 1);
}

function applyZenVisibility() {
    const tbody = document.querySelector("#results-table tbody");
    if (!tbody) return;
    const limit = getZenVisibleLimit();
    const rows = Array.from(tbody.children || []);
    rows.forEach((tr, idx) => {
        if (!zenModeEnabled) {
            tr.classList.remove("zen-hidden");
            return;
        }
        if (Number.isFinite(limit) && idx >= limit) {
            tr.classList.add("zen-hidden");
        } else {
            tr.classList.remove("zen-hidden");
        }
    });
}

function relocateZenToggle(inZen) {
    const toggle = document.getElementById("zen-toggle");
    if (!toggle) return;
    if (!zenToggleHome) {
        zenToggleHome = toggle.parentElement;
        zenToggleNextSibling = toggle.nextElementSibling;
    }
    const slot = document.getElementById("zen-slot");
    if (inZen) {
        if (slot && toggle.parentElement !== slot) {
            slot.appendChild(toggle);
        }
    } else if (zenToggleHome && toggle.parentElement !== zenToggleHome) {
        if (zenToggleNextSibling && zenToggleNextSibling.parentNode === zenToggleHome) {
            zenToggleHome.insertBefore(toggle, zenToggleNextSibling);
        } else {
            zenToggleHome.appendChild(toggle);
        }
    }
}

function setZenMode(enabled) {
    zenModeEnabled = Boolean(enabled);
    const pane = document.getElementById("results-pane");
    const toggle = document.getElementById("zen-toggle");
    if (pane) pane.classList.toggle("zen-mode", zenModeEnabled);
    document.documentElement.setAttribute("data-zen", zenModeEnabled ? "true" : "false");
    relocateZenToggle(zenModeEnabled);
    if (toggle) {
        toggle.classList.toggle("active", zenModeEnabled);
        toggle.setAttribute("aria-pressed", zenModeEnabled ? "true" : "false");
    }
    if (zenModeEnabled) {
        resetZenLimit();
    }
    applyZenVisibility();
    updateLoadMoreButton();
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
            <td class="snippet" title="${escapeHtml(snippetText)}"><div class="snippet-content">${snippetHtml || ""}</div></td>
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
    applyZenVisibility();
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
    if (zenModeEnabled) {
        const tbody = document.querySelector("#results-table tbody");
        const totalRows = tbody ? tbody.children.length : 0;
        const limit = getZenVisibleLimit();
        const maxIdx = ZEN_STEPS.length - 1;
        const hasNextStep = zenStepIdx < maxIdx && totalRows > limit;
        if (hasNextStep) {
            const nextLimit = ZEN_STEPS[Math.min(zenStepIdx + 1, maxIdx)];
            btn.textContent = Number.isFinite(nextLimit) ? `Mehr anzeigen (${nextLimit})` : "Alle anzeigen";
        } else {
            btn.textContent = "Mehr laden";
        }
        btn.disabled = searchLoading;
        btn.classList.toggle("hidden", !hasNextStep);
        return;
    }
    btn.textContent = "Mehr laden";
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
    const max = Math.max(min + 120, window.innerWidth - 260);
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
    let dragging = false;

    const onDrag = (e) => {
        if (!dragging) return;
        if (e.buttons === 0) {
            stopDrag();
            return;
        }
        const clientX = e.clientX ?? (e.touches && e.touches[0]?.clientX) ?? startX;
        const delta = startX - clientX;
        const newWidth = startWidth + delta;
        e.preventDefault();
        setPanelWidth(newWidth);
        positionPreview();
    };

    const stopDrag = () => {
        if (!dragging) return;
        dragging = false;
        document.removeEventListener("pointermove", onDrag, true);
        document.removeEventListener("pointerup", stopDrag, true);
        document.body.classList.remove("resizing-preview");
        sessionStorage.setItem(PANEL_WIDTH_KEY, String(getPanelWidthPx()));
        setTimeout(() => {
            resizingPreview = false;
        }, 50);
    };

    handle.addEventListener("pointerdown", (e) => {
        if (!previewIsOpen()) return;
        dragging = true;
        resizingPreview = true;
        startX = e.clientX ?? (e.touches && e.touches[0]?.clientX) ?? 0;
        startWidth = getPanelWidthPx();
        try {
            handle.setPointerCapture(e.pointerId);
        } catch (_) {
            /* ignore */
        }
        document.body.classList.add("resizing-preview");
        document.addEventListener("pointermove", onDrag, true);
        document.addEventListener("pointerup", stopDrag, true);
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

function renderSearchFavorites() {
    const dropdown = document.getElementById("fav-dropdown");
    if (!dropdown) return;
    dropdown.innerHTML = "";
    const list = document.createElement("div");
    list.className = "fav-list";
    const title = document.createElement("h4");
    title.textContent = "Gespeicherte Suchen";
    dropdown.appendChild(title);
    if (!searchFavorites.length) {
        const empty = document.createElement("div");
        empty.className = "fav-item";
        empty.style.cursor = "default";
        empty.innerHTML = '<span class="label">Keine Favoriten</span>';
        list.appendChild(empty);
    } else {
        searchFavorites.forEach((item, idx) => {
            const row = document.createElement("div");
            row.className = "fav-item";
            row.dataset.value = item;
            const label = document.createElement("span");
            label.className = "label";
            label.textContent = item;
            const remove = document.createElement("button");
            remove.className = "fav-remove";
            remove.type = "button";
            remove.dataset.idx = idx;
            remove.setAttribute("aria-label", "Favorit entfernen");
            remove.textContent = "×";
            row.appendChild(label);
            row.appendChild(remove);
            list.appendChild(row);
        });
    }
    dropdown.appendChild(list);
}

function addSearchFavorite(value) {
    const trimmed = (value || "").trim();
    if (!trimmed) return false;
    const existing = searchFavorites.filter((v) => v.toLowerCase() !== trimmed.toLowerCase());
    searchFavorites = [trimmed, ...existing].slice(0, 10);
    writeSearchFavorites(searchFavorites);
    renderSearchFavorites();
    showToast({ type: "success", title: "Suche gespeichert", message: trimmed });
    return true;
}

function removeSearchFavorite(idx) {
    if (idx < 0 || idx >= searchFavorites.length) return;
    searchFavorites.splice(idx, 1);
    writeSearchFavorites(searchFavorites);
    renderSearchFavorites();
}

function openFavDropdown() {
    const dropdown = document.getElementById("fav-dropdown");
    const star = document.getElementById("search-fav");
    if (!dropdown || !star) return;
    renderSearchFavorites();
    dropdown.classList.add("visible");
    star.classList.add("active");
}

function closeFavDropdown() {
    const dropdown = document.getElementById("fav-dropdown");
    const star = document.getElementById("search-fav");
    if (!dropdown || !star) return;
    dropdown.classList.remove("visible");
    star.classList.remove("active");
}

function toggleFavDropdown() {
    const dropdown = document.getElementById("fav-dropdown");
    if (!dropdown) return;
    if (dropdown.classList.contains("visible")) {
        closeFavDropdown();
    } else {
        openFavDropdown();
    }
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
    let cleaned = false;
    const cleanup = () => {
        if (cleaned) return;
        cleaned = true;
        setTimeout(() => iframe.remove(), 500);
    };
    iframe.onload = () => {
        try {
            iframe.contentWindow.focus();
            iframe.contentWindow.onafterprint = cleanup;
            iframe.contentWindow.print();
        } catch (err) {
            console.error("Print fehlgeschlagen", err);
            cleanup();
        }
    };
    setTimeout(cleanup, 20000);
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
setupThemeSwitcher();
setupSearchModeSwitch();
setupTypeFilterSwitch();
setupTimeFilterChips();
setupSourceFilter();
setupAdminControls();
setupDeleteConfirm();
setupRenameDialog();
setupMoveDialog();
refreshAdminStatus();
document.getElementById("search-input").addEventListener("input", debounceSearch);
setupSearchFavorites();
setupAboutOverlay();
const zenToggle = document.getElementById("zen-toggle");
if (zenToggle) {
    setZenMode(false);
    zenToggle.addEventListener("click", () => {
        setZenMode(!zenModeEnabled);
        scheduleFocusSearchInput();
    });
}

const themeToggleHeader = document.getElementById("theme-toggle-header");
if (themeToggleHeader) {
    themeToggleHeader.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleThemeMenu();
    });
}
const navHome = document.getElementById("nav-home");
if (navHome) {
    navHome.addEventListener("click", () => {
        window.location.href = "/";
    });
}
const navHomeLinks = document.querySelectorAll("a[href='/']");
if (!navHome && navHomeLinks.length === 0) {
    // Fallback, falls Buttons durch Templates ohne Script geladen werden
    const btns = document.querySelectorAll("#nav-home");
    btns.forEach((btn) => {
        btn.addEventListener("click", () => (window.location.href = "/"));
    });
}

const loadMoreBtn = document.getElementById("load-more");
if (loadMoreBtn) {
    loadMoreBtn.addEventListener("click", () => {
        if (zenModeEnabled) {
            const tbody = document.querySelector("#results-table tbody");
            const totalRows = tbody ? tbody.children.length : 0;
            const beforeIdx = zenStepIdx;
            advanceZenStep(totalRows);
            applyZenVisibility();
            updateLoadMoreButton();
            if (beforeIdx !== zenStepIdx) {
                scheduleFocusSearchInput();
            }
            return;
        }
        if (searchHasMore && !searchLoading) {
            search({ append: true });
        }
    });
}

// Header menu
function setupHeaderMenu() {
    const toggle = document.getElementById("header-menu");
    const dropdown = document.getElementById("header-menu-dropdown");
    if (!toggle || !dropdown) {
        console.error("[menu] Header-Menü konnte nicht initialisiert werden (Toggle/Dropdown fehlt).", { toggle: !!toggle, dropdown: !!dropdown });
        return;
    }
    const repositionDropdown = () => {
        const rect = toggle.getBoundingClientRect();
        dropdown.style.position = "fixed";
        dropdown.style.top = `${rect.bottom + 10}px`;
        dropdown.style.right = `${Math.max(10, window.innerWidth - rect.right)}px`;
    };
    const closeMenu = () => {
        dropdown.classList.add("hidden");
        toggle.setAttribute("aria-expanded", "false");
    };
    const openMenu = () => {
        repositionDropdown();
        dropdown.classList.remove("hidden");
        toggle.setAttribute("aria-expanded", "true");
    };
    const toggleMenu = () => {
        if (dropdown.classList.contains("hidden")) openMenu();
        else closeMenu();
    };
    toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleMenu();
    });
    document.addEventListener("click", (e) => {
        if (!dropdown.contains(e.target) && e.target !== toggle) {
            closeMenu();
        }
    });
    window.addEventListener("resize", () => {
        if (!dropdown.classList.contains("hidden")) repositionDropdown();
    });
    document.addEventListener("scroll", () => {
        if (!dropdown.classList.contains("hidden")) repositionDropdown();
    }, true);
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeMenu();
    });
    const adminBtn = document.getElementById("admin-button-menu");
    if (adminBtn) {
        adminBtn.addEventListener("click", () => {
            closeMenu();
            if (typeof window.openAdminModal === "function") {
                window.openAdminModal({ forceReauth: true });
                return;
            }
            const adminTrigger = document.getElementById("admin-button");
            if (adminTrigger) {
                adminTrigger.classList.remove("hidden");
                adminTrigger.click();
            } else {
                const modal = document.getElementById("admin-modal");
                if (modal) {
                    modal.classList.remove("hidden");
                } else {
                    console.error("[admin] Admin-Overlay nicht gefunden, Menü-Click ohne Wirkung.");
                }
            }
        });
    } else {
        console.error("[menu] Admin-Menüeintrag fehlt.");
    }
    const feedbackBtn = document.getElementById("feedback-trigger-menu");
    if (feedbackBtn) {
        feedbackBtn.addEventListener("click", () => {
            closeMenu();
            const trigger = document.getElementById("feedback-trigger");
            if (trigger) trigger.click();
        });
    }

    const aboutBtn = document.getElementById("menu-about");
    if (aboutBtn) {
        aboutBtn.addEventListener("click", () => {
            closeMenu();
            if (typeof window.openAboutOverlay === "function") {
                window.openAboutOverlay();
            }
        });
    }
}

function setupAboutOverlay() {
    const overlay = document.getElementById("about-overlay");
    const okBtn = document.getElementById("about-ok");
    const titleEl = document.getElementById("about-title");
    const sloganEl = document.getElementById("about-slogan");
    const descEl = document.getElementById("about-description");
    if (!overlay || !okBtn) {
        return;
    }
    const setOpen = (state) => {
        overlay.classList.toggle("hidden", !state);
        document.body.classList.toggle("dialog-open", state);
        document.body.style.overflow = state ? "hidden" : "";
    };
    const fillContent = () => {
        if (titleEl) {
            titleEl.textContent = window.appTitle || document.title || "Index-Suche";
        }
        if (sloganEl) {
            sloganEl.textContent = window.appSlogan || "";
            sloganEl.classList.toggle("hidden", !sloganEl.textContent);
        }
        if (descEl && !descEl.textContent) {
            descEl.textContent = "Index-Suche mit Explorer-UI, Quarantäne-Workflow und Metrics.";
        }
    };
    const open = () => {
        fillContent();
        setOpen(true);
    };
    const close = () => setOpen(false);
    okBtn.addEventListener("click", close);
    overlay.addEventListener("click", (e) => {
        if (e.target === overlay) close();
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !overlay.classList.contains("hidden")) {
            close();
        }
    });
    window.openAboutOverlay = open;
}

function handleInitialQueryActions() {
    const params = new URLSearchParams(window.location.search || "");
    const pending = {
        admin: params.has("admin"),
        feedback: params.has("feedback"),
        about: params.has("about"),
    };
    let handled = false;
    if (pending.admin && typeof window.openAdminModal === "function") {
        window.openAdminModal({ forceReauth: true });
        handled = true;
    }
    if (pending.feedback && typeof window.openFeedbackOverlay === "function") {
        window.openFeedbackOverlay();
        handled = true;
    }
    if (pending.about && typeof window.openAboutOverlay === "function") {
        window.openAboutOverlay();
        handled = true;
    }
    if (handled) {
        params.delete("admin");
        params.delete("feedback");
        params.delete("about");
        const next = params.toString();
        const hash = window.location.hash || "";
        const target = next ? `${window.location.pathname}?${next}${hash}` : `${window.location.pathname}${hash}`;
        window.history.replaceState({}, "", target);
    }
}

setupHeaderMenu();

setupPopup();
setupPreviewResizer();
focusSearchInput();

// Column resize
function setupResizableColumns() {
    const headerRow = document.querySelector("#results-table thead tr");
    const tbody = document.querySelector("#results-table tbody");
    const colgroup = document.querySelector("#results-table colgroup");
    if (!headerRow) return;
    const MIN_COL_WIDTH = 80;

    function setColumnWidth(colIdx, widthPx) {
        const value = `${Math.max(MIN_COL_WIDTH, widthPx)}px`;
        const th = headerRow.querySelectorAll("th")[colIdx];
        if (th) th.style.width = value;
        if (colgroup) {
            const col = colgroup.querySelector(`col[data-col-idx="${colIdx}"]`);
            if (col) col.style.width = value;
        }
        if (!tbody) return;
        tbody.querySelectorAll(`tr td:nth-child(${colIdx + 1})`).forEach((td) => {
            td.style.width = value;
        });
    }

    const stored = JSON.parse(localStorage.getItem("colWidths") || "{}");
    headerRow.querySelectorAll("th").forEach((th, index) => {
        th.style.position = "relative";
        if (stored[index]) {
            const parsed = parseFloat(stored[index]);
            if (Number.isFinite(parsed)) {
                setColumnWidth(index, parsed);
            } else {
                th.style.width = stored[index];
            }
        } else if (th.dataset.width) {
            th.style.width = th.dataset.width;
            if (colgroup) {
                const col = colgroup.querySelector(`col[data-col-idx="${index}"]`);
                if (col) col.style.width = th.dataset.width;
            }
        }
        const handle = document.createElement("div");
        handle.className = "resize-handle";
        let startX = 0;
        let startWidth = 0;
        let nextWidth = 0;
        let hasNext = index < headerRow.querySelectorAll("th").length - 1;
        const table = document.getElementById("results-table");
        let dragging = false;

        handle.addEventListener("click", (e) => e.stopPropagation());
        handle.addEventListener("pointerdown", (e) => {
            resizingColumn = true;
            dragging = true;
            startX = e.clientX ?? 0;
            startWidth = parseFloat(getComputedStyle(th).width) || th.offsetWidth;
            hasNext = index < headerRow.querySelectorAll("th").length - 1;
            if (hasNext) {
                const nextTh = headerRow.querySelectorAll("th")[index + 1];
                nextWidth = parseFloat(getComputedStyle(nextTh).width) || nextTh.offsetWidth;
            } else {
                nextWidth = 0;
            }
            try {
                handle.setPointerCapture(e.pointerId);
            } catch (_) {
                /* ignore */
            }
            document.body.classList.add("dragging-columns");
            if (tbody) {
                tbody.style.pointerEvents = "none";
            }
            document.addEventListener("pointermove", onDrag, true);
            document.addEventListener("pointerup", stopDrag, true);
            e.preventDefault();
        });

        function onDrag(e) {
            if (!dragging) return;
            if (e.buttons === 0) {
                stopDrag();
                return;
            }
            const clientX = e.clientX ?? startX;
            const delta = clientX - startX;
            if (hasNext) {
                const total = startWidth + nextWidth;
                const newCurrent = Math.min(Math.max(MIN_COL_WIDTH, startWidth + delta), total - MIN_COL_WIDTH);
                const newNext = total - newCurrent;
                setColumnWidth(index, newCurrent);
                setColumnWidth(index + 1, newNext);
            } else {
                const tableWidth = table ? table.clientWidth : window.innerWidth;
                const maxCurrent = Math.max(MIN_COL_WIDTH, tableWidth - MIN_COL_WIDTH * (headerRow.querySelectorAll("th").length - 1));
                const newWidth = Math.min(Math.max(MIN_COL_WIDTH, startWidth + delta), maxCurrent);
                setColumnWidth(index, newWidth);
            }
            e.preventDefault();
        }

        function stopDrag() {
            if (!dragging) return;
            dragging = false;
            document.removeEventListener("pointermove", onDrag, true);
            document.removeEventListener("pointerup", stopDrag, true);
            document.body.classList.remove("dragging-columns");
            const widths = {};
            headerRow.querySelectorAll("th").forEach((th2, idx) => {
                if (th2.style.width) widths[idx] = th2.style.width;
            });
            localStorage.setItem("colWidths", JSON.stringify(widths));
            if (tbody) {
                tbody.style.pointerEvents = "";
            }
            setTimeout(() => {
                resizingColumn = false;
            }, 50);
        }
        th.appendChild(handle);
    });

    // Ensure initial widths apply to cols as well (for datasets without stored widths)
    headerRow.querySelectorAll("th").forEach((th, idx) => {
        const w = th.style.width || th.dataset.width;
        if (w) setColumnWidth(idx, parseFloat(w));
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
            showToast({ type: "error", title: "Löschen fehlgeschlagen", message: detail });
            return;
        }
        removeResultRow(pendingDeleteId);
        closeDeleteConfirm();
        showToast({ type: "success", title: "Gelöscht", message: "Datei in Quarantäne verschoben." });
    } catch (_) {
        if (errorEl) {
            errorEl.textContent = "Verschieben fehlgeschlagen.";
            errorEl.classList.remove("hidden");
        }
        if (confirmBtn) confirmBtn.disabled = false;
        showToast({ type: "error", title: "Löschen fehlgeschlagen", message: "Aktion konnte nicht ausgeführt werden." });
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
            showToast({ type: "error", title: "Umbenennen fehlgeschlagen", message: detail });
            return;
        }
        const data = await res.json();
        applyRenameResult(data);
        closeRenameDialog();
        showToast({ type: "success", title: "Umbenannt", message: data?.display_name || input.value || "Erfolg" });
    } catch (_) {
        errorEl.textContent = "Umbenennen fehlgeschlagen.";
        errorEl.classList.remove("hidden");
        confirmBtn.disabled = false;
        showToast({ type: "error", title: "Umbenennen fehlgeschlagen", message: "Aktion konnte nicht ausgeführt werden." });
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

// Move dialog
let moveState = {
    open: false,
    docId: null,
    source: "",
    currentPath: "",
    currentName: "",
    selection: null,
    mode: "move",
    nodes: new Map(),
    loading: false,
};

function resetMoveState() {
    moveState = {
        open: false,
        docId: null,
        source: "",
        currentPath: "",
        currentName: "",
        selection: null,
        mode: "move",
        nodes: new Map(),
        loading: false,
    };
    updateMoveTargetPath();
}

function handleMoveAction(id) {
    const row = document.querySelector(`#results-table tbody tr[data-id="${id}"]`);
    const sourceLabel = row?.dataset.source || "";
    if (!canUseFileOpsForSource(sourceLabel)) {
        closeContextMenu();
        return;
    }
    closeContextMenu();
    showMoveDialog(id, "move");
}

function handleCopyAction(id) {
    const row = document.querySelector(`#results-table tbody tr[data-id="${id}"]`);
    const sourceLabel = row?.dataset.source || "";
    if (!canUseFileOpsForSource(sourceLabel)) {
        closeContextMenu();
        return;
    }
    closeContextMenu();
    showMoveDialog(id, "copy");
}

function normalizeRelPath(path) {
    const text = String(path || "").replace(/\\/g, "/");
    const trimmed = text.replace(/^\/+/, "").replace(/\/+$/, "");
    return trimmed;
}

function getMoveNode(path) {
    return moveState.nodes.get(path || "") || null;
}

function upsertMoveNode(node) {
    const key = `${node.source || ""}::${node.path || ""}`;
    moveState.nodes.set(key, { ...node, pathKey: key });
}

function splitMoveKey(key) {
    const [sourcePart, ...rest] = String(key || "").split("::");
    const source = sourcePart || "";
    const path = rest.join("::") || "";
    return { source, path };
}

function updateMoveTargetPath() {
    const targetEl = document.getElementById("move-target-path");
    if (!targetEl) return;
    if (!moveState.selection) {
        targetEl.textContent = "Bitte Ordner wählen";
        return;
    }
    const { source, path } = splitMoveKey(moveState.selection || "");
    const label = path ? `${source ? source + "/" : ""}${path}` : source || "/";
    targetEl.textContent = label || "Bitte Ordner wählen";
}

async function fetchMoveChildren(source, path) {
    const params = new URLSearchParams();
    if (source) params.set("source", source);
    if (path) params.set("path", path);
    const res = await fetch(`/api/files/tree?${params.toString()}`);
    if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || "Verzeichnisse konnten nicht geladen werden.");
    }
    const data = await res.json();
    const entries = Array.isArray(data.entries) ? data.entries : [];
    return entries.map((entry) => ({
        name: entry.name || "",
        path: normalizeRelPath(entry.path || ""),
        hasChildren: Boolean(entry.has_children),
        source: entry.source || source || moveState.source,
        expanded: false,
        loaded: false,
        loading: false,
        children: [],
    }));
}

async function loadMoveNode(path) {
    const node = getMoveNode(path);
    if (!node) return;
    node.loading = true;
    renderMoveTree();
    try {
        const { source, path: relPath } = splitMoveKey(path);
        const children = await fetchMoveChildren(node.source || source || moveState.source, relPath);
        node.children = children.map((child) => `${child.source || node.source || source || ""}::${child.path || ""}`);
        upsertMoveNode({ ...node, loaded: true, loading: false });
        children.forEach((child) => {
            upsertMoveNode({ ...child, expanded: false });
        });
    } catch (err) {
        node.loading = false;
        const errorEl = document.getElementById("move-error");
        if (errorEl) {
            errorEl.textContent = err.message || "Verzeichnisse konnten nicht geladen werden.";
            errorEl.classList.remove("hidden");
        }
    } finally {
        const current = getMoveNode(path);
        if (current) {
            current.loading = false;
            upsertMoveNode(current);
        }
        renderMoveTree();
    }
}

function renderMoveTree() {
    const tree = document.getElementById("move-tree");
    const confirmBtn = document.getElementById("move-confirm");
    if (!tree) return;
    const prevScrollTop = tree.scrollTop;
    const prevScrollLeft = tree.scrollLeft;
    const fragment = document.createDocumentFragment();

    function renderBranch(pathKey, depth = 0) {
        const node = getMoveNode(pathKey);
        if (!node) return null;
        const branch = document.createElement("div");
        branch.className = "move-branch";
        branch.dataset.depth = String(depth);
        const row = document.createElement("div");
        row.className = "move-node";
        row.dataset.pathKey = pathKey || "";
        row.setAttribute("role", "treeitem");
        row.setAttribute("aria-level", String(depth + 1));
        row.setAttribute("aria-expanded", node.hasChildren ? String(Boolean(node.expanded)) : "false");
        row.style.paddingLeft = `${depth * 16 + 8}px`;
        const isSelected = pathKey === (moveState.selection || "");
        if (isSelected) {
            row.classList.add("is-selected");
            row.setAttribute("aria-selected", "true");
        } else {
            row.setAttribute("aria-selected", "false");
        }
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "move-node__toggle";
        toggle.textContent = node.loading ? "…" : node.hasChildren ? (node.expanded ? "▾" : "▸") : "•";
        toggle.disabled = !node.hasChildren || node.loading;
        toggle.addEventListener("click", () => toggleMoveNode(pathKey));

        const radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "move-target";
        radio.value = pathKey || "";
        radio.checked = isSelected;
        radio.addEventListener("change", () => {
            moveState.selection = pathKey || "";
            updateMoveTargetPath();
            renderMoveTree();
        });

        const label = document.createElement("span");
        label.className = "move-node__label";
        label.textContent = node.path ? node.name : node.source || "/";
        label.title = node.path ? `${node.source || ""}/${node.path}` : node.source || "/";
        label.addEventListener("click", () => {
            moveState.selection = pathKey || "";
            updateMoveTargetPath();
            renderMoveTree();
        });

        const status = document.createElement("span");
        status.className = "move-node__status";
        if (node.loading) {
            status.textContent = "Laden…";
        } else if (node.children && node.children.length) {
            status.textContent = "";
        } else if (node.hasChildren) {
            status.textContent = "";
        } else {
            status.textContent = "";
        }

        row.addEventListener("click", (ev) => {
            if (ev.target === toggle) return;
            if (ev.target === radio) return;
            moveState.selection = pathKey || "";
            updateMoveTargetPath();
            renderMoveTree();
        });

        row.addEventListener("dblclick", () => {
            if (node.hasChildren) {
                toggleMoveNode(pathKey);
            }
        });

        row.appendChild(toggle);
        row.appendChild(radio);
        row.appendChild(label);
        if (status.textContent) row.appendChild(status);

        branch.appendChild(row);

        if (node.expanded && node.children && node.children.length) {
            const childrenWrap = document.createElement("div");
            childrenWrap.className = "move-children";
            node.children.forEach((childKey) => {
                const childBranch = renderBranch(childKey, depth + 1);
                if (childBranch) childrenWrap.appendChild(childBranch);
            });
            branch.appendChild(childrenWrap);
        }
        return branch;
    }

    moveState.nodes.forEach((node, key) => {
        if (key.endsWith("::")) {
            const rendered = renderBranch(key);
            if (rendered) fragment.appendChild(rendered);
        }
    });

    tree.replaceChildren(fragment);
    tree.scrollTop = prevScrollTop;
    tree.scrollLeft = prevScrollLeft;
    if (confirmBtn) {
        confirmBtn.disabled = moveState.selection === null || moveState.selection === undefined;
    }
    updateMoveTargetPath();
}

function toggleMoveNode(path) {
    const node = getMoveNode(path);
    if (!node || node.loading || !node.hasChildren) return;
    if (!node.loaded) {
        node.expanded = true;
        upsertMoveNode(node);
        loadMoveNode(path);
        return;
    }
    node.expanded = !node.expanded;
    upsertMoveNode(node);
    renderMoveTree();
}

async function showMoveDialog(docId, mode = "move") {
    const modal = document.getElementById("move-dialog");
    const nameEl = document.getElementById("move-current-name");
    const pathEl = document.getElementById("move-current-path");
    const errorEl = document.getElementById("move-error");
    const confirmBtn = document.getElementById("move-confirm");
    if (!modal || !nameEl || !pathEl || !errorEl || !confirmBtn) return;
    const row = document.querySelector(`#results-table tbody tr[data-id="${docId}"]`);
    const sourceLabel = row?.dataset.source || "";
    const name = row?.querySelector(".filename")?.textContent?.trim() || "";
    const path = row?.querySelector(".path-cell")?.textContent?.trim() || "";
    moveState.open = true;
    moveState.docId = docId;
    moveState.source = sourceLabel;
    moveState.currentName = name;
    moveState.currentPath = path;
    moveState.selection = null;
    moveState.mode = mode === "copy" ? "copy" : "move";
    moveState.nodes = new Map();
    updateMoveTargetPath();
    errorEl.textContent = "";
    errorEl.classList.add("hidden");
    confirmBtn.disabled = true;
    confirmBtn.textContent = mode === "copy" ? "Kopieren" : "Verschieben";
    nameEl.textContent = name || "Datei";
    pathEl.textContent = path || "";
    // Roots: alle bereitgestellten Quellen laden
    const rootEntries = await fetchMoveChildren(null, "");
    rootEntries.forEach((entry) => {
        const key = `${entry.source || entry.name || ""}::`;
        upsertMoveNode({
            name: entry.name || entry.source || "Quelle",
            path: "",
            source: entry.source || entry.name || "",
            hasChildren: true,
            expanded: entry.source === sourceLabel,
            loaded: false,
            loading: false,
            children: [],
        });
    });
    modal.classList.remove("hidden");
    // Auto-expand aktuelle Quelle
    if (sourceLabel) {
        await loadMoveNode(`${sourceLabel}::`);
    }
    renderMoveTree();
}

function closeMoveDialog() {
    const modal = document.getElementById("move-dialog");
    if (modal) modal.classList.add("hidden");
    resetMoveState();
}

function applyMoveResult(data) {
    const id = data?.doc_id;
    if (!id) return;
    const newPath = data?.display_path || data?.new_path || "";
    const newSource = data?.source || "";
    const row = document.querySelector(`#results-table tbody tr[data-id="${id}"]`);
    if (row) {
        if (newSource) {
            row.dataset.source = newSource;
        }
        const pathEl = row.querySelector(".path-cell");
        if (pathEl && newPath) {
            pathEl.textContent = newPath;
            pathEl.title = newPath;
        }
    }
    if (currentDocId && String(currentDocId) === String(id)) {
        const pathHeader = document.getElementById("preview-path");
        if (pathHeader && newPath) pathHeader.textContent = newPath;
    }
}

async function submitMove() {
    if (!moveState.docId) return;
    if (!moveState.selection) return;
    const errorEl = document.getElementById("move-error");
    const confirmBtn = document.getElementById("move-confirm");
    if (errorEl) {
        errorEl.textContent = "";
        errorEl.classList.add("hidden");
    }
    confirmBtn.disabled = true;
    const { source: targetSource, path: targetDir } = splitMoveKey(moveState.selection || "");
    try {
        const endpoint = moveState.mode === "copy" ? "copy" : "move";
        const res = await fetch(`/api/files/${moveState.docId}/${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ target_dir: targetDir, target_source: targetSource }),
        });
        if (!res.ok) {
            let detail = moveState.mode === "copy" ? "Kopieren fehlgeschlagen." : "Verschieben fehlgeschlagen.";
            try {
                const data = await res.json();
                detail = data.detail || detail;
            } catch (_) {
                /* ignore */
            }
            throw new Error(detail);
        }
        const data = await res.json();
        if (moveState.mode === "copy") {
            closeMoveDialog();
            search({ append: false });
            showToast({
                type: "success",
                title: "Kopiert",
                message: `${moveState.currentName || "Datei"} nach ${targetSource ? targetSource + "/" : ""}${targetDir || "/"} kopiert.`,
            });
        } else {
            applyMoveResult(data);
            closeMoveDialog();
            showToast({
                type: "success",
                title: "Verschoben",
                message: `${moveState.currentName || "Datei"} nach ${targetSource ? targetSource + "/" : ""}${targetDir || "/"} verschoben.`,
            });
        }
    } catch (err) {
        if (errorEl) {
            errorEl.textContent =
                err.message || (moveState.mode === "copy" ? "Kopieren fehlgeschlagen." : "Verschieben fehlgeschlagen.");
            errorEl.classList.remove("hidden");
        }
        showToast({
            type: "error",
            title: moveState.mode === "copy" ? "Kopieren fehlgeschlagen" : "Verschieben fehlgeschlagen",
            message: err?.message || "Aktion konnte nicht ausgeführt werden.",
        });
    } finally {
        if (confirmBtn) {
            confirmBtn.disabled = moveState.selection === null || moveState.selection === undefined;
        }
    }
}

function handleMoveDialogKeydown(e) {
    if (!moveState.open) return;
    const modal = document.getElementById("move-dialog");
    if (!modal || modal.classList.contains("hidden")) return;
    if (e.key === "Escape") {
        e.preventDefault();
        closeMoveDialog();
    } else if (e.key === "Enter") {
        const confirmBtn = document.getElementById("move-confirm");
        if (confirmBtn && !confirmBtn.disabled) {
            e.preventDefault();
            submitMove();
        }
    }
}

function setupMoveDialog() {
    const modal = document.getElementById("move-dialog");
    if (!modal) return;
    const closeBtn = document.getElementById("move-close");
    const cancelBtn = document.getElementById("move-cancel");
    const confirmBtn = document.getElementById("move-confirm");
    closeBtn?.addEventListener("click", closeMoveDialog);
    cancelBtn?.addEventListener("click", closeMoveDialog);
    confirmBtn?.addEventListener("click", submitMove);
    document.addEventListener("keydown", handleMoveDialogKeydown, true);
    modal.addEventListener("click", (e) => {
        if (e.target === modal) closeMoveDialog();
    });
}

// Context menu
const FUTURE_CONTEXT_MENU_FLAGS = {
    adminEntry: false,
    filterEntry: false,
};

const CONTEXT_MENU_SECTIONS = [
    { id: "view", label: "Ansehen", order: 1 },
    { id: "export", label: "Exportieren", order: 2 },
    { id: "manage", label: "Verwalten", order: 3 },
    { id: "more", label: "Mehr", order: 4 },
];

const CONTEXT_MENU_ITEMS = [
    { id: "preview", label: "Preview", group: "view", order: 1, icon: "eye", shortcut: "Enter", handler: (ctx) => openPreview(ctx.id, true) },
    { id: "popup", label: "Pop-up", group: "view", order: 2, icon: "window", handler: (ctx) => openPopupForRow(ctx.id) },
    { id: "download", label: "Download", group: "export", order: 1, icon: "download", handler: (ctx) => window.open(`/api/document/${ctx.id}/file?download=1`, "_blank") },
    { id: "print", label: "Drucken", group: "export", order: 2, icon: "print", handler: (ctx) => printDocument(ctx.id) },
    {
        id: "copy",
        label: "Kopieren…",
        group: "manage",
        order: 1,
        icon: "copy",
        visibleIf: (ctx) => ctx.canManageFile,
        enabledIf: (ctx) => ctx.canManageFile,
        caption: (ctx, enabled) => (!enabled ? "Admin & Quelle bereit" : ""),
        handler: (ctx) => handleCopyAction(ctx.id),
    },
    {
        id: "rename",
        label: "Umbenennen…",
        group: "manage",
        order: 1,
        icon: "edit",
        shortcut: "F2",
        visibleIf: (ctx) => ctx.canManageFile,
        enabledIf: (ctx) => ctx.canManageFile,
        caption: (ctx, enabled) => (!enabled ? "Admin & Quelle bereit" : ""),
        handler: (ctx) => handleRenameAction(ctx.id),
    },
    {
        id: "move",
        label: "Verschieben…",
        group: "manage",
        order: 1.5,
        icon: "folder",
        visibleIf: (ctx) => ctx.canManageFile,
        enabledIf: (ctx) => ctx.canManageFile,
        caption: (ctx, enabled) => (!enabled ? "Admin & Quelle bereit" : ""),
        handler: (ctx) => handleMoveAction(ctx.id),
    },
    {
        id: "delete",
        label: "Löschen",
        group: "manage",
        order: 2,
        icon: "trash",
        danger: true,
        visibleIf: (ctx) => ctx.canManageFile,
        enabledIf: (ctx) => ctx.canManageFile,
        caption: (ctx, enabled) => (!enabled ? "Admin & Quelle bereit" : ""),
        handler: (ctx) => handleDeleteAction(ctx.id),
    },
    {
        id: "feedback",
        label: "Feedback senden",
        group: "more",
        order: 1,
        icon: "feedback",
        visibleIf: () => feedbackFeatureEnabled(),
        handler: () => openFeedbackFromMenu(),
    },
    {
        id: "admin",
        label: "Als Admin…",
        group: "more",
        order: 2,
        icon: "shield",
        visibleIf: () => FUTURE_CONTEXT_MENU_FLAGS.adminEntry,
        enabledIf: () => false,
        caption: "Geplant",
    },
    {
        id: "filter",
        label: "Filter anpassen",
        group: "more",
        order: 3,
        icon: "filter",
        visibleIf: () => FUTURE_CONTEXT_MENU_FLAGS.filterEntry,
        enabledIf: () => false,
        caption: "Geplant",
    },
];

let contextMenuEl = null;
let contextMenuButtons = [];
let contextMenuVisibleItems = [];
let contextMenuActiveIndex = -1;

function resolveSectionLabel(id) {
    const found = CONTEXT_MENU_SECTIONS.find((section) => section.id === id);
    return found ? found.label : id;
}

function getContextMenuContext(id) {
    const row = document.querySelector(`#results-table tbody tr[data-id="${id}"]`);
    if (!row) return null;
    const name = row.querySelector(".filename")?.textContent?.trim() || "Dokument";
    const pathLabel = row.querySelector(".path-cell")?.textContent?.trim() || "";
    const sourceLabel = row.dataset.source || "";
    const extensionLabel = (fileExtension(name) || "").replace(".", "").toUpperCase() || "DOC";
    return {
        id,
        name,
        path: pathLabel,
        sourceLabel,
        extensionLabel,
        canManageFile: canUseFileOpsForSource(sourceLabel),
        rowRect: row.getBoundingClientRect(),
    };
}

function hydrateContextMenuItems(ctx) {
    const sectionOrder = new Map(CONTEXT_MENU_SECTIONS.map((section, idx) => [section.id, section.order ?? idx]));
    return CONTEXT_MENU_ITEMS.map((item, idx) => {
        const visible = typeof item.visibleIf === "function" ? item.visibleIf(ctx) : true;
        const enabled = typeof item.enabledIf === "function" ? item.enabledIf(ctx) : true;
        const caption = typeof item.caption === "function" ? item.caption(ctx, enabled) : item.caption;
        return {
            ...item,
            visible,
            enabled,
            caption: caption || "",
            __order: idx,
            sectionOrder: sectionOrder.get(item.group) ?? 99,
        };
    })
        .filter((item) => item.visible !== false)
        .sort((a, b) => {
            if (a.sectionOrder !== b.sectionOrder) return a.sectionOrder - b.sectionOrder;
            if ((a.order ?? 0) !== (b.order ?? 0)) return (a.order ?? 0) - (b.order ?? 0);
            return (a.__order ?? 0) - (b.__order ?? 0);
        });
}

function createContextMenuIcon(name) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.classList.add("context-menu__icon");
    const addPath = (d, opts = {}) => {
        const path = document.createElementNS(ns, "path");
        path.setAttribute("d", d);
        path.setAttribute("fill", opts.fill || "none");
        path.setAttribute("stroke", opts.stroke || "currentColor");
        path.setAttribute("stroke-width", opts.strokeWidth || "1.6");
        path.setAttribute("stroke-linecap", opts.lineCap || "round");
        path.setAttribute("stroke-linejoin", opts.lineJoin || "round");
        svg.appendChild(path);
    };
    switch (name) {
        case "eye":
            addPath("M1.5 12s4-7.5 10.5-7.5S22.5 12 22.5 12s-4 7.5-10.5 7.5S1.5 12 1.5 12z");
            addPath("M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z");
            break;
        case "window":
            addPath("M4.5 6.5A2 2 0 0 1 6.5 4.5h11a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2z");
            addPath("M4.5 10.5h15");
            addPath("M9.5 4.5v6");
            break;
        case "download":
            addPath("M12 3v12");
            addPath("M8.5 11.5 12 15l3.5-3.5");
            addPath("M5 19h14", { strokeWidth: "1.4" });
            break;
        case "copy":
            addPath("M9 5.5h8a1.5 1.5 0 0 1 1.5 1.5v10a1.5 1.5 0 0 1-1.5 1.5h-8a1.5 1.5 0 0 1-1.5-1.5v-10A1.5 1.5 0 0 1 9 5.5z");
            addPath("M6 8.5h-1a1.5 1.5 0 0 0-1.5 1.5v9a1.5 1.5 0 0 0 1.5 1.5h9a1.5 1.5 0 0 0 1.5-1.5v-1", { strokeWidth: "1.4" });
            break;
        case "print":
            addPath("M7 9.5v-4a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v4");
            addPath("M7 15.5h10v5H7z");
            addPath("M6 12h12a1 1 0 0 0 1-1V9a1 1 0 0 0-1-1H6a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1z");
            break;
        case "edit":
            addPath("M5 16.75V19h2.25l9.9-9.9a1.5 1.5 0 0 0 0-2.12l-1.13-1.13a1.5 1.5 0 0 0-2.12 0z");
            addPath("M13.75 6.25 16.5 9");
            break;
        case "trash":
            addPath("M6.5 8.5h11l-.7 10.1a1.5 1.5 0 0 1-1.5 1.4H8.7a1.5 1.5 0 0 1-1.5-1.4z");
            addPath("M5 6.5h14");
            addPath("M10 5.5h4l.7 1H9.3z");
            break;
        case "feedback":
            addPath("M6 6h12a1 1 0 0 1 1 1v8.5a1 1 0 0 1-1 1H9.5L6 19.5V7a1 1 0 0 1 1-1z");
            addPath("M9 10h6", { strokeWidth: "1.4" });
            addPath("M9 13h4", { strokeWidth: "1.4" });
            break;
        case "check":
            addPath("M5 12.5 10 17l9-10");
            break;
        case "alert":
            addPath("M12 4.5 4.5 19h15z");
            addPath("M12 10v4");
            addPath("M12 16.5h.01", { strokeWidth: "2" });
            break;
        case "info":
            addPath("M12 4.5a7.5 7.5 0 1 1 0 15 7.5 7.5 0 0 1 0-15z");
            addPath("M12 9h.01", { strokeWidth: "2" });
            addPath("M11.2 12h1.6V16h-1.6z");
            break;
        case "folder":
            addPath("M3.5 7a1.5 1.5 0 0 1 1.5-1.5h4l1.2 1.6H19a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 16V7z");
            addPath("M3.5 9.5h16");
            break;
        case "shield":
            addPath("M12 3.5 19 7v5.5c0 4-2.9 7.7-7 8.5-4.1-.8-7-4.5-7-8.5V7z");
            break;
        case "filter":
            addPath("M4.5 6h15L14 12.5v5l-4-2.5v-2.5z");
            break;
        default:
            svg.innerHTML = "";
            addPath("M12 5.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13z");
    }
    return svg;
}

function createToastIcon(type) {
    const map = { success: "check", error: "alert", info: "info" };
    return createContextMenuIcon(map[type] || "info");
}

function createContextMenuHeader(ctx) {
    const header = document.createElement("div");
    header.className = "context-menu__header";
    const badge = document.createElement("div");
    badge.className = "context-menu__pill";
    badge.textContent = ctx.extensionLabel || "DOC";
    const textWrap = document.createElement("div");
    textWrap.className = "context-menu__title-wrap";
    const title = document.createElement("div");
    title.className = "context-menu__title";
    title.textContent = ctx.name || "Dokument";
    title.title = ctx.name || "";
    const path = document.createElement("div");
    path.className = "context-menu__path";
    const subline = ctx.path || (ctx.sourceLabel ? `Quelle: ${ctx.sourceLabel}` : `ID ${ctx.id}`);
    path.textContent = subline;
    path.title = subline;
    textWrap.appendChild(title);
    textWrap.appendChild(path);
    header.appendChild(badge);
    header.appendChild(textWrap);
    return header;
}

function createContextMenuButton(item) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "context-menu__item";
    btn.dataset.action = item.id;
    btn.setAttribute("role", "menuitem");
    if (item.danger) {
        btn.classList.add("danger");
    }
    if (!item.enabled) {
        btn.disabled = true;
        btn.setAttribute("aria-disabled", "true");
    }
    const icon = createContextMenuIcon(item.icon);
    if (icon) {
        btn.appendChild(icon);
    }
    const textWrap = document.createElement("span");
    textWrap.className = "context-menu__text";
    const label = document.createElement("span");
    label.className = "context-menu__label";
    label.textContent = item.label;
    textWrap.appendChild(label);
    if (item.caption) {
        const hint = document.createElement("span");
        hint.className = "context-menu__hint";
        hint.textContent = item.caption;
        textWrap.appendChild(hint);
    }
    btn.appendChild(textWrap);
    if (item.shortcut) {
        const shortcut = document.createElement("span");
        shortcut.className = "context-menu__shortcut";
        shortcut.textContent = item.shortcut;
        btn.appendChild(shortcut);
    }
    return btn;
}

function renderContextMenu(ctx) {
    const items = hydrateContextMenuItems(ctx);
    if (!items.length) return null;
    const menu = document.createElement("div");
    menu.className = "context-menu";
    menu.setAttribute("role", "menu");
    menu.tabIndex = -1;
    menu.appendChild(createContextMenuHeader(ctx));
    let currentGroup = null;
    let listEl = null;
    const buttons = [];
    items.forEach((item) => {
        if (item.group !== currentGroup) {
            currentGroup = item.group;
            const section = document.createElement("div");
            section.className = "context-menu__section";
            const title = document.createElement("div");
            title.className = "context-menu__section-title";
            title.textContent = resolveSectionLabel(item.group);
            listEl = document.createElement("div");
            listEl.className = "context-menu__list";
            section.appendChild(title);
            section.appendChild(listEl);
            menu.appendChild(section);
        }
        const btn = createContextMenuButton(item);
        buttons.push(btn);
        listEl.appendChild(btn);
    });
    menu.addEventListener("click", (ev) => handleContextMenuClick(ev, ctx));
    return { menu, items, buttons };
}

function positionContextMenu(menu, triggerEvent, anchorRect) {
    const margin = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const fallbackX = anchorRect ? anchorRect.left + Math.min(anchorRect.width / 2, 160) : vw / 2;
    const fallbackY = anchorRect ? anchorRect.top + Math.min(anchorRect.height / 2, 80) : vh / 2;
    const clickX = Number.isFinite(triggerEvent?.clientX) ? triggerEvent.clientX : fallbackX;
    const clickY = Number.isFinite(triggerEvent?.clientY) ? triggerEvent.clientY : fallbackY;
    const rect = menu.getBoundingClientRect();
    let left = clickX;
    let top = clickY;
    if (left + rect.width > vw - margin) {
        left = Math.max(margin, vw - rect.width - margin);
    }
    if (top + rect.height > vh - margin) {
        top = Math.max(margin, vh - rect.height - margin);
    }
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
}

function focusContextMenuItem(targetIndex, { wrap = true } = {}) {
    if (!contextMenuButtons.length) return;
    const total = contextMenuButtons.length;
    let idx = Math.min(Math.max(targetIndex, 0), total - 1);
    for (let i = 0; i < total; i++) {
        const candidate = wrap ? (idx + i) % total : Math.min(total - 1, idx + i);
        const btn = contextMenuButtons[candidate];
        if (btn && !btn.disabled) {
            btn.focus({ preventScroll: true });
            contextMenuActiveIndex = candidate;
            return;
        }
    }
}

function focusFirstContextMenuItem() {
    focusContextMenuItem(0);
}

function moveContextMenuFocus(step) {
    if (!contextMenuButtons.length) return;
    let idx = contextMenuActiveIndex >= 0 ? contextMenuActiveIndex : 0;
    for (let i = 0; i < contextMenuButtons.length; i++) {
        idx = (idx + step + contextMenuButtons.length) % contextMenuButtons.length;
        const btn = contextMenuButtons[idx];
        if (btn && !btn.disabled) {
            btn.focus({ preventScroll: true });
            contextMenuActiveIndex = idx;
            return;
        }
    }
}

function handleContextMenuClick(ev, ctx) {
    const btn = ev.target.closest(".context-menu__item");
    if (!btn || btn.disabled) return;
    const action = btn.dataset.action;
    const item = contextMenuVisibleItems.find((entry) => entry.id === action);
    if (item && typeof item.handler === "function") {
        item.handler(ctx);
    }
    if (!item || item.closeOnSelect !== false) {
        closeContextMenu();
    }
}

function handleContextMenuOutside(e) {
    if (!contextMenuEl) return;
    if (e.target.closest(".context-menu")) return;
    closeContextMenu();
}

function handleContextMenuKeydown(e) {
    if (!contextMenuEl) return;
    if (e.key === "ArrowDown") {
        e.preventDefault();
        moveContextMenuFocus(1);
    } else if (e.key === "ArrowUp") {
        e.preventDefault();
        moveContextMenuFocus(-1);
    } else if (e.key === "Home") {
        e.preventDefault();
        focusContextMenuItem(0, { wrap: false });
    } else if (e.key === "End") {
        e.preventDefault();
        focusContextMenuItem(contextMenuButtons.length - 1, { wrap: false });
    } else if (e.key === "Escape") {
        e.preventDefault();
        closeContextMenu();
    }
}

function handleContextMenuScroll() {
    closeContextMenu();
}

function attachContextMenuGuards() {
    document.addEventListener("mousedown", handleContextMenuOutside);
    document.addEventListener("keydown", handleContextMenuKeydown, true);
    window.addEventListener("resize", closeContextMenu);
    window.addEventListener("scroll", handleContextMenuScroll, true);
}

function detachContextMenuGuards() {
    document.removeEventListener("mousedown", handleContextMenuOutside);
    document.removeEventListener("keydown", handleContextMenuKeydown, true);
    window.removeEventListener("resize", closeContextMenu);
    window.removeEventListener("scroll", handleContextMenuScroll, true);
}

function showContextMenu(e, id) {
    e?.preventDefault?.();
    const ctx = getContextMenuContext(id);
    if (!ctx) return;
    closeContextMenu();
    const rendered = renderContextMenu(ctx);
    if (!rendered) return;
    contextMenuEl = rendered.menu;
    contextMenuVisibleItems = rendered.items;
    contextMenuButtons = rendered.buttons;
    contextMenuActiveIndex = -1;
    contextMenuEl.style.visibility = "hidden";
    document.body.appendChild(contextMenuEl);
    positionContextMenu(contextMenuEl, e, ctx.rowRect);
    contextMenuEl.style.visibility = "visible";
    attachContextMenuGuards();
    focusFirstContextMenuItem();
}

function closeContextMenu() {
    if (contextMenuEl) {
        detachContextMenuGuards();
        contextMenuEl.remove();
    }
    contextMenuEl = null;
    contextMenuVisibleItems = [];
    contextMenuButtons = [];
    contextMenuActiveIndex = -1;
}

function openFeedbackFromMenu() {
    if (!feedbackFeatureEnabled()) return;
    if (typeof window.openFeedbackOverlay === "function") {
        window.openFeedbackOverlay();
        return;
    }
    const trigger = document.getElementById("feedback-trigger");
    if (trigger) {
        trigger.click();
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
        closeMoveDialog();
        const adminModal = document.getElementById("admin-modal");
        if (adminModal && !adminModal.classList.contains("hidden")) {
            adminModal.classList.add("hidden");
        }
        return;
    }
    if (!contextMenuEl && (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10"))) {
        const activeRow = document.querySelector("#results-table tbody tr.active") || document.querySelector("#results-table tbody tr");
        const rowId = activeRow?.dataset.id;
        if (!rowId) return;
        e.preventDefault();
        const rect = activeRow.getBoundingClientRect();
        showContextMenu(
            {
                preventDefault() {},
                clientX: rect.left + Math.min(rect.width / 2, 160),
                clientY: rect.top + Math.min(rect.height / 2, 80),
            },
            rowId
        );
    }
});

window.addEventListener("resize", positionPreview);

function clampZoom(value) {
    return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function readSavedZoom() {
    try {
        localStorage.removeItem(APP_ZOOM_KEY);
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

function setupToasts() {
    const stack = document.getElementById("toast-stack");
    if (!stack) return;
    const MAX_TOASTS = 4;

    function removeToast(el) {
        if (!el) return;
        el.remove();
    }

    showToast = function showToast({ type = "info", title = "", message = "", timeout = 5000 } = {}) {
        const toast = document.createElement("div");
        toast.className = `toast toast--${type}`;
        toast.setAttribute("role", "status");
        const icon = createToastIcon(type);
        icon.classList.add("toast__icon");
        const body = document.createElement("div");
        body.className = "toast__body";
        const ttl = document.createElement("div");
        ttl.className = "toast__title";
        ttl.textContent = title || (type === "success" ? "Erfolg" : type === "error" ? "Fehler" : "Hinweis");
        const msg = document.createElement("div");
        msg.className = "toast__message";
        msg.textContent = message || "";
        body.appendChild(ttl);
        if (message) body.appendChild(msg);
        const closeBtn = document.createElement("button");
        closeBtn.className = "toast__close";
        closeBtn.type = "button";
        closeBtn.setAttribute("aria-label", "Schließen");
        closeBtn.textContent = "×";
        closeBtn.addEventListener("click", () => removeToast(toast));

        toast.appendChild(icon);
        toast.appendChild(body);
        toast.appendChild(closeBtn);

        stack.prepend(toast);
        while (stack.children.length > MAX_TOASTS) {
            stack.lastChild?.remove();
        }
        const t = window.setTimeout(() => removeToast(toast), timeout);
        toast.addEventListener("click", () => {
            window.clearTimeout(t);
            removeToast(toast);
        });
    };
}

// Feedback overlay
const MAX_FEEDBACK_LEN = 5000;

function setupFeedback() {
    const enabled = feedbackFeatureEnabled();
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

    window.openFeedbackOverlay = openOverlay;

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
            showToast({ type: "success", title: "Feedback gesendet", message: "Vielen Dank für Ihr Feedback." });
        } catch (err) {
            setStatus("error", "Verbindung fehlgeschlagen. Bitte erneut versuchen.");
            showToast({ type: "error", title: "Feedback fehlgeschlagen", message: "Senden nicht möglich." });
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
setupToasts();
handleInitialQueryActions();
