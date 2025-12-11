async function search() {
    const q = document.getElementById("search-input").value;
    if (!q) return;
    const source = document.getElementById("source-filter").value;
    const ext = document.getElementById("ext-filter").value;
    const params = new URLSearchParams({ q });
    if (source) params.append("source", source);
    if (ext) params.append("extension", ext.replace(".", "").toLowerCase());

    const res = await fetch(`/api/search?${params.toString()}`);
    const data = await res.json();
    renderResults(data.results || []);
}

function renderResults(results) {
    const tbody = document.querySelector("#results-table tbody");
    tbody.innerHTML = "";
    results.forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${row.filename}</td>
            <td>${row.source}</td>
            <td>${row.extension}</td>
            <td>${(row.size_bytes / 1024).toFixed(1)} KB</td>
            <td>${new Date(row.mtime * 1000).toLocaleString()}</td>
            <td title="${row.path}">${row.path}</td>
            <td class="snippet">${row.snippet || ""}</td>
        `;
        tr.addEventListener("click", () => openPreview(row.id || row.doc_id));
        tbody.appendChild(tr);
    });
}

async function openPreview(id) {
    if (!id) return;
    const res = await fetch(`/api/document/${id}`);
    if (!res.ok) return;
    const doc = await res.json();
    document.getElementById("download-link").href = `/api/document/${id}/file`;
    renderPreviewContent(doc, document.getElementById("preview-content"));
}

function renderPreviewContent(doc, container) {
    container.innerHTML = "";
    const ext = (doc.extension || "").toLowerCase();
    if (ext === ".pdf") {
        const iframe = document.createElement("iframe");
        const encoded = encodeURIComponent(`/api/document/${doc.id}/file`);
        iframe.src = `https://mozilla.github.io/pdf.js/web/viewer.html?file=${encoded}`;
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

function setupPopup() {
    const popup = document.getElementById("preview-popup");
    const popupBody = document.getElementById("popup-body");
    document.getElementById("open-popup").addEventListener("click", async () => {
        popup.classList.remove("hidden");
        const link = document.getElementById("download-link").href;
        if (link) {
            // Nachladen des aktuellen Dokuments für die Popup-Darstellung
            const id = link.split("/").slice(-2, -1)[0];
            const res = await fetch(`/api/document/${id}`);
            if (res.ok) {
                const doc = await res.json();
                renderPreviewContent(doc, popupBody);
            }
        }
    });
    document.getElementById("close-popup").addEventListener("click", () => {
        popup.classList.add("hidden");
        popupBody.innerHTML = "";
    });
}

document.getElementById("search-btn").addEventListener("click", search);
document.getElementById("search-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") search();
});
setupPopup();
