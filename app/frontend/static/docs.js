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
        if (stored && typeof stored === "string") {
            return stored;
        }
    } catch (_) {
        /* ignore */
    }
    return null;
}

function applyTheme(themeId) {
    const fallback = normalizeTheme(themeId) || DEFAULT_THEME;
    document.documentElement.setAttribute("data-theme", fallback);
    const labelEl = document.getElementById("theme-toggle-label");
    if (labelEl) labelEl.textContent = themeLabel(fallback);
    return fallback;
}

function persistTheme(themeId) {
    const next = applyTheme(themeId);
    try {
        localStorage.setItem(THEME_KEY, next);
    } catch (_) {
        /* ignore */
    }
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
    if (!toggle || !menu) return;
    const initial = normalizeTheme(document.documentElement.getAttribute("data-theme")) || readStoredTheme() || DEFAULT_THEME;
    persistTheme(initial);
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
        if (e.key === "Escape") closeThemeMenu();
    });
    renderThemeMenu(initial);
    const headerToggle = document.getElementById("theme-toggle-header");
    if (headerToggle) {
        headerToggle.addEventListener("click", (e) => {
            e.stopPropagation();
            toggleThemeMenu();
        });
    }
}

function setupAnchorScroll() {
    const links = document.querySelectorAll(".docs-nav .nav-link[href^='#']");
    links.forEach((link) => {
        link.addEventListener("click", (e) => {
            const targetId = link.getAttribute("href").slice(1);
            const target = document.getElementById(targetId);
            if (!target) return;
            e.preventDefault();
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        });
    });
}

setupThemeSwitcher();
setupAnchorScroll();
