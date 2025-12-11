let currentDocId = null;
let searchTimer = null;
let sortState = { key: null, dir: "asc" };
let resizingColumn = false;
let resizingPreview = false;
const PANEL_WIDTH_KEY = "previewWidth";

applySavedPreviewWidth();

async function search() {
    const q = document.getElementById("search-input").value;
    const ext = document.getElementById("ext-filter").value;
    const time = document.getElementById("time-filter").value;
    const params = new URLSearchParams({ q });
    if (ext) params.append("extension", ext.replace(".", "").toLowerCase());
    if (time) params.append("time_filter", time);
    if (sortState.key) {
        params.append("sort_key", sortState.key);
        params.append("sort_dir", sortState.dir);
    }

    const res = await fetch(`/api/search?${params.toString()}`);
    const data = await res.json();
    renderResults(data.results || []);
    populateFilters(data.results || []);
    updateSortIndicators();
}

function debounceSearch() {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(search, 250);
}

function renderResults(results) {
    const tbody = document.querySelector("#results-table tbody");
    tbody.innerHTML = "";
    results.forEach((row) => {
        const tr = document.createElement("tr");
        const rowId = row.id || row.doc_id;
        tr.dataset.id = rowId;
        const sizeLabel = typeof row.size_bytes === "number" ? `${(row.size_bytes / 1024).toFixed(1)} KB` : "–";
        const mtimeLabel = row.mtime ? new Date(row.mtime * 1000).toLocaleString() : "–";
        tr.innerHTML = `
            <td>${row.filename}</td>
            <td>${row.extension}</td>
            <td>${sizeLabel}</td>
            <td>${mtimeLabel}</td>
            <td title="${row.path}">${row.path}</td>
            <td class="snippet">${row.snippet || ""}</td>
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

async function openPreview(id, showPanel = false) {
    if (!id) return;
    currentDocId = id;
    markActiveRow(id);
    const res = await fetch(`/api/document/${id}`);
    if (!res.ok) {
        closePreviewPanel();
        return;
    }
    const doc = await res.json();
    if (currentDocId !== id) return;
    document.getElementById("download-link").href = `/api/document/${id}/file?download=1`;
    renderPreviewContent(doc, document.getElementById("preview-content"));
    if (showPanel) {
        showPreviewPanel();
    }
}

function showPreviewPanel() {
    document.getElementById("preview-panel").classList.remove("hidden");
    document.getElementById("layout").classList.add("preview-open");
}

function closePreviewPanel() {
    document.getElementById("preview-panel").classList.add("hidden");
    document.getElementById("layout").classList.remove("preview-open");
    markActiveRow(null);
    currentDocId = null;
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
}

function applySavedPreviewWidth() {
    const saved = sessionStorage.getItem(PANEL_WIDTH_KEY);
    if (!saved) return;
    const parsed = parseFloat(saved);
    if (!Number.isFinite(parsed)) return;
    setPanelWidth(parsed);
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

function renderPreviewContent(doc, container) {
    container.innerHTML = "";
    const ext = (doc.extension || "").toLowerCase();
    if (ext === ".pdf") {
        const iframe = document.createElement("iframe");
        iframe.src = `/api/document/${doc.id}/file#toolbar=0&navpanes=0&view=FitH`;
        iframe.className = "pdf-frame";
        container.appendChild(iframe);
        return;
    }

    if (ext === ".msg") {
        const header = document.createElement("div");
        header.innerHTML = `
            <div><strong>Von:</strong> ${doc.msg_from || ""}</div>
            <div><strong>An:</strong> ${doc.msg_to || ""}</div>
            <div><strong>CC:</strong> ${doc.msg_cc || ""}</div>
            <div><strong>Betreff:</strong> ${doc.msg_subject || doc.title_or_subject || ""}</div>
            <div><strong>Datum:</strong> ${doc.msg_date || ""}</div>
            <hr/>
        `;
        const body = document.createElement("pre");
        body.textContent = doc.content || "";
        container.appendChild(header);
        container.appendChild(body);
        return;
    }

    const pre = document.createElement("pre");
    pre.textContent = doc.content || "";
    container.appendChild(pre);
}

function openPopupForRow(id) {
    if (!id) return;
    const url = `/viewer?id=${id}`;
    const w = Math.floor(window.screen.availWidth * 0.72);
    const h = Math.floor(window.screen.availHeight * 0.78);
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
    const url = `/api/document/${id}/file`;
    const win = window.open(url, "_blank");
    if (!win) return;
    let printed = false;
    const triggerPrint = () => {
        if (printed) return;
        printed = true;
        try {
            win.focus();
            win.print();
        } catch (err) {
            console.error("Print fehlgeschlagen", err);
        }
    };
    if (win.document?.readyState === "complete") {
        setTimeout(triggerPrint, 120);
    } else {
        win.addEventListener("load", () => setTimeout(triggerPrint, 150));
        setTimeout(triggerPrint, 1200);
    }
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
document.getElementById("ext-filter").addEventListener("change", search);
document.getElementById("time-filter").addEventListener("change", search);

setupPopup();
setupPreviewResizer();

// Column resize
function setupResizableColumns() {
    const headerRow = document.querySelector("#results-table thead tr");
    const stored = JSON.parse(localStorage.getItem("colWidths") || "{}");
    headerRow.querySelectorAll("th").forEach((th, index) => {
        th.style.position = "relative";
        if (stored[index]) th.style.width = stored[index];
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

function populateFilters(results) {
    const exts = new Set();
    results.forEach((r) => {
        if (r.extension) exts.add(r.extension);
    });
    const extSelect = document.getElementById("ext-filter");
    const currentExt = extSelect.value;
    const extOptions = ['<option value="">Typ (alle / Reset)</option>'].concat(
        Array.from(exts)
            .sort((a, b) => a.localeCompare(b))
            .map((x) => `<option value="${x}">${x}</option>`)
    );
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
