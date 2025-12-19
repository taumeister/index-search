(function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  const isLocalhost = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
  const isSecure = window.isSecureContext || isLocalhost;
  if (!isSecure) {
    console.warn("[pwa] Service Worker Registrierung nur in sicheren Kontexten möglich.");
    return;
  }

  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/service-worker.js", { scope: "/" })
      .then((registration) => {
        console.info("[pwa] Service Worker registriert", registration.scope);
      })
      .catch((err) => {
        console.warn("[pwa] Service Worker Registrierung fehlgeschlagen", err);
      });
  });
})();
