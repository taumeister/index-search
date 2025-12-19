const SW_VERSION = "1.0.0";

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (!event || !event.request || event.request.method !== "GET") return;
  event.respondWith(
    (async () => {
      try {
        return await fetch(event.request);
      } catch (_err) {
        return Response.error();
      }
    })(),
  );
});
