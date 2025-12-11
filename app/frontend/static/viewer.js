function sizeWindow() {
    const w = Math.max(780, Math.floor(window.screen.availWidth * 0.6));
    const h = Math.max(640, Math.floor(window.screen.availHeight * 0.7));
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
    const res = await fetch(`/api/document/${id}`);
    if (!res.ok) {
        document.getElementById("content").innerHTML = "<p>Dokument nicht gefunden.</p>";
        return;
    }
    const doc = await res.json();
    render(doc);
    sizeWindow();
}

function render(doc) {
    document.getElementById("title").textContent = doc.filename || "Dokument";
    document.getElementById("download-link").href = `/api/document/${doc.id}/file?download=1`;

    const container = document.getElementById("content");
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

function printCurrent() {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("id");
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

function bindActions() {
    const btn = document.getElementById("print-btn");
    if (btn) {
        btn.addEventListener("click", printCurrent);
    }
}

loadDoc();
bindActions();
