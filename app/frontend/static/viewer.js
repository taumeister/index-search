const APP_ZOOM_KEY = "appZoom";
const DEFAULT_ZOOM = 1;
const MIN_ZOOM = 0.6;
const MAX_ZOOM = 1.6;
bootstrapZoom();

function sizeWindow() {
    const w = Math.max(540, Math.floor(window.screen.availWidth * 0.5));
    const h = Math.max(480, Math.floor(window.screen.availHeight * 0.6));
    const left = Math.floor((window.screen.availWidth - w) / 2);
    const top = Math.floor((window.screen.availHeight - h) / 2);
    try {
        window.resizeTo(w, h);
        window.moveTo(left, top);
    } catch (e) {
        // einige Browser blocken move/resize
    }
}

async function loadDoc() {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("id");
    if (!id) return;
    document.title = `Viewer - Dokument ${id}`;
    const headers = buildAuthHeaders();
    const res = await fetch(`/api/document/${id}`, { headers, credentials: "include" });
    if (!res.ok) {
        document.getElementById("content").innerHTML = `<p>Dokument nicht gefunden oder Zugriff verweigert (${res.status}).</p>`;
        return;
    }
    const doc = await res.json();
    window.__currentDoc = doc;
    render(doc);
    sizeWindow();
}

function render(doc) {
    document.getElementById("title").textContent = doc.filename || "Dokument";
    const dl = document.getElementById("download-link");
    if (dl) {
        dl.dataset.docid = doc.id;
        dl.href = `/api/document/${doc.id}/file?download=1`;
    }

    const container = document.getElementById("content");
    container.innerHTML = "";
    const ext = (doc.extension || "").toLowerCase();

    if (ext === ".pdf") {
        const iframe = document.createElement("iframe");
        iframe.className = "pdf-frame";
        iframe.title = "Dokument-Viewer";
        iframe.setAttribute("aria-label", "Dokument-Viewer");
        container.appendChild(iframe);
        let iframeSrcSet = false;
        const setSrc = (src) => {
            if (iframeSrcSet) return;
            iframe.src = src;
            iframeSrcSet = true;
        };
        const fallback = window.setTimeout(() => {
            setSrc(`/api/document/${doc.id}/file#toolbar=0&navpanes=0&view=FitH`);
        }, 900);
        fetchFileAsBlob(doc.id)
            .then((url) => {
                window.clearTimeout(fallback);
                setSrc(`${url}#toolbar=0&navpanes=0&view=FitH`);
            })
            .catch(() => {
                window.clearTimeout(fallback);
                setSrc(`/api/document/${doc.id}/file#toolbar=0&navpanes=0&view=FitH`);
            });
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

function printCurrent() {
    const doc = window.__currentDoc;
    const id = doc?.id;
    if (!id) return;
    const url = `/api/document/${id}/file#toolbar=0&navpanes=0&view=FitH`;
    const iframe = document.createElement("iframe");
    iframe.style.position = "fixed";
    iframe.style.right = "-9999px";
    iframe.style.width = "1px";
    iframe.style.height = "1px";
    iframe.src = url;
    const cleanup = () => setTimeout(() => iframe.remove(), 1600);
    let printed = false;
    iframe.onload = () => {
        try {
            iframe.contentWindow.focus();
            iframe.contentWindow.print();
            printed = true;
        } catch (err) {
            console.error("Print fehlgeschlagen", err);
        } finally {
            cleanup();
        }
    };
    document.body.appendChild(iframe);

    // Fallback: kleines Fenster öffnen, drucken, wieder schließen
    setTimeout(() => {
        if (printed) return;
        const win = window.open(url, "_blank", "width=600,height=700,toolbar=no,location=no,menubar=no,resizable=yes,scrollbars=yes");
        if (!win) return;
        const closeWin = () => {
            try {
                win.close();
            } catch (_) {
                /* ignore */
            }
        };
        const tryPrint = () => {
            try {
                win.focus();
                win.print();
            } catch (err) {
                console.error("Print fallback fehlgeschlagen", err);
            } finally {
                setTimeout(closeWin, 300);
            }
        };
        win.addEventListener("load", () => setTimeout(tryPrint, 200));
        setTimeout(tryPrint, 1200);
    }, 800);
}

function bindActions() {
    const btn = document.getElementById("print-btn");
    if (btn) {
        btn.addEventListener("click", printCurrent);
    }
    const closeBtn = document.getElementById("close-viewer");
    if (closeBtn) {
        closeBtn.addEventListener("click", () => {
            try {
                window.close();
            } catch (_) {
                /* ignore */
            }
        });
    }
    const dl = document.getElementById("download-link");
    if (dl) {
        dl.addEventListener("click", async (e) => {
            e.preventDefault();
            const doc = window.__currentDoc;
            const id = doc?.id;
            if (!id) return;
            try {
                const headers = buildAuthHeaders();
        const resp = await fetch(`/api/document/${id}/file`, { headers, credentials: "include" });
                if (!resp.ok) throw new Error(`Download fehlgeschlagen (${resp.status})`);
                const blob = await resp.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = doc.filename || `dokument-${id}`;
                document.body.appendChild(a);
                a.click();
                setTimeout(() => {
                    a.remove();
                    URL.revokeObjectURL(url);
                }, 500);
            } catch (err) {
                console.error(err);
            }
        });
    }
}

loadDoc();
bindActions();
function buildAuthHeaders() {
    const headers = { "X-Internal-Auth": "1" };
    try {
        const cookieMatch = document.cookie.match(/app_secret=([^;]+)/);
        if (cookieMatch && cookieMatch[1]) {
            headers["X-App-Secret"] = decodeURIComponent(cookieMatch[1]);
        }
    } catch (_) {
        /* ignore */
    }
    return headers;
}

async function fetchFileAsBlob(docId) {
    const headers = buildAuthHeaders();
    const resp = await fetch(`/api/document/${docId}/file`, { headers, credentials: "include" });
    if (!resp.ok) {
        throw new Error(`Download fehlgeschlagen (${resp.status})`);
    }
    const blob = await resp.blob();
    return URL.createObjectURL(blob);
}

function clampZoom(value) {
    return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function readSavedZoom() {
    try {
        const raw = localStorage.getItem(APP_ZOOM_KEY);
        const parsed = parseFloat(raw);
        if (Number.isFinite(parsed)) return clampZoom(parsed);
    } catch (_) {
        /* ignore */
    }
    return DEFAULT_ZOOM;
}

function applyZoom(value) {
    const clamped = clampZoom(value);
    document.documentElement.style.setProperty("--app-zoom", clamped);
    return clamped;
}

function bootstrapZoom() {
    applyZoom(readSavedZoom());
    window.addEventListener("storage", (e) => {
        if (e.key === APP_ZOOM_KEY) {
            applyZoom(readSavedZoom());
        }
    });
}
