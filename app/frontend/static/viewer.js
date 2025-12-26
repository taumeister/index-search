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
    const filename = doc.filename || `Dokument ${doc.id || ""}`.trim();
    const safeFileName = (filename || `dokument-${doc.id || ""}`.trim()).replace(/[\\/]/g, "_");
    document.title = filename;
    document.getElementById("title").textContent = filename;
    const dl = document.getElementById("download-link");
    if (dl) {
        dl.dataset.docid = doc.id;
        dl.href = `/api/document/${doc.id}/file/${encodeURIComponent(safeFileName)}?download=1`;
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
        iframe.src = `/api/document/${doc.id}/file/${encodeURIComponent(safeFileName)}#toolbar=0&navpanes=0&view=FitH`;
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
    const filename = doc.filename || `dokument-${id}`;
    const safeFileName = (filename || `dokument-${id}`).replace(/[\\/]/g, "_");
    const url = `/api/document/${id}/file/${encodeURIComponent(safeFileName)}#toolbar=0&navpanes=0&view=FitH`;
    const iframe = document.createElement("iframe");
    // Größeres, aber unsichtbares iframe, damit kein Reflow/Minimieren sichtbar wird.
    iframe.style.position = "fixed";
    iframe.style.top = "0";
    iframe.style.left = "0";
    iframe.style.width = "100vw";
    iframe.style.height = "100vh";
    iframe.style.opacity = "0";
    iframe.style.pointerEvents = "none";
    iframe.src = url;
    const cleanup = () => setTimeout(() => iframe.remove(), 20000);
    iframe.onload = () => {
        try {
            iframe.contentWindow.focus();
            iframe.contentWindow.print();
        } catch (err) {
            console.error("Print fehlgeschlagen", err);
        } finally {
            setTimeout(() => {
                try {
                    window.focus();
                } catch (_) {
                    /* ignore */
                }
            }, 100);
            cleanup();
        }
    };
    document.body.appendChild(iframe);
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
            // Direktlink nutzen, damit der Download-Button nicht blockiert.
            window.open(`/api/document/${id}/file?download=1`, "_blank");
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
