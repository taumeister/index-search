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

document.addEventListener("DOMContentLoaded", setupAnchorScroll);
