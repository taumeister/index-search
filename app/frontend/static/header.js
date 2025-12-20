(function initHeader() {
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
            return localStorage.getItem(THEME_KEY);
        } catch (_) {
            return null;
        }
    }

    function applyTheme(themeId) {
        const next = normalizeTheme(themeId) || DEFAULT_THEME;
        document.documentElement.setAttribute("data-theme", next);
        return next;
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
        const headerToggle = document.getElementById("theme-toggle-header");
        const initial = normalizeTheme(document.documentElement.getAttribute("data-theme")) || readStoredTheme() || DEFAULT_THEME;
        if (!toggle || !menu) {
            applyTheme(initial);
            const labelEl = document.getElementById("theme-toggle-label");
            if (labelEl) labelEl.textContent = themeLabel(initial);
            return;
        }
        persistTheme(initial);
        toggle.addEventListener("click", (e) => {
            e.stopPropagation();
            toggleThemeMenu();
        });
        if (headerToggle) {
            headerToggle.addEventListener("click", (e) => {
                e.stopPropagation();
                toggleThemeMenu();
            });
        }
        document.addEventListener("click", (e) => {
            if (!menu.contains(e.target) && e.target !== toggle && e.target !== headerToggle) {
                closeThemeMenu();
            }
        });
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") closeThemeMenu();
        });
        renderThemeMenu(initial);
    }

    function handleAdminAction(closeMenu) {
        if (typeof window.openAdminModal === "function") {
            window.openAdminModal({ forceReauth: true });
            return;
        }
        if (closeMenu) closeMenu();
        window.location.href = "/?admin=1";
    }

    function handleFeedbackAction(closeMenu) {
        if (typeof window.openFeedbackOverlay === "function") {
            window.openFeedbackOverlay();
            return;
        }
        if (closeMenu) closeMenu();
        window.location.href = "/?feedback=1";
    }

    function handleAboutAction(closeMenu) {
        if (typeof window.openAboutOverlay === "function") {
            window.openAboutOverlay();
            return;
        }
        if (closeMenu) closeMenu();
        window.location.href = "/?about=1";
    }

    function setupHeaderMenu() {
        const toggle = document.getElementById("header-menu");
        const dropdown = document.getElementById("header-menu-dropdown");
        if (!toggle || !dropdown) {
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
        document.addEventListener(
            "scroll",
            () => {
                if (!dropdown.classList.contains("hidden")) repositionDropdown();
            },
            true
        );
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") closeMenu();
        });

        const adminBtn = document.getElementById("admin-button-menu");
        if (adminBtn) {
            adminBtn.addEventListener("click", () => handleAdminAction(closeMenu));
        }
        const feedbackBtn = document.getElementById("feedback-trigger-menu");
        if (feedbackBtn) {
            feedbackBtn.addEventListener("click", () => handleFeedbackAction(closeMenu));
        }
        const aboutBtn = document.getElementById("menu-about");
        if (aboutBtn) {
            aboutBtn.addEventListener("click", () => handleAboutAction(closeMenu));
        }
    }

    function setupNavHome() {
        const navHome = document.getElementById("nav-home");
        if (!navHome) return;
        navHome.addEventListener("click", (e) => {
            e.preventDefault();
            window.location.href = "/";
        });
    }

    document.addEventListener("DOMContentLoaded", () => {
        setupThemeSwitcher();
        setupHeaderMenu();
        setupNavHome();
    });
})();
