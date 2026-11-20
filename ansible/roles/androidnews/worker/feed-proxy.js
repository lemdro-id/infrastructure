// AndroidNews feed proxy for lemdro.id.
// Fetches only the two Valnet RSS feeds that block the OVH server IP.
// Not an open proxy: paths are a hard allowlist, and query strings are ignored.

const FEEDS = Object.freeze({
  "/androidpolice": "https://www.androidpolice.com/feed/news/",
  "/xda": "https://www.xda-developers.com/feed/news/",
});

const UPSTREAM_UA = "AndroidNewsBot/2.0 (lemdro.id; via cloudflare worker)";
const UPSTREAM_ACCEPT =
  "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8";
const CACHE_TTL_SECONDS = 600;

export default {
  async fetch(request, _env, ctx) {
    if (request.method !== "GET") {
      return notFound();
    }

    const url = new URL(request.url);
    let path = url.pathname;
    if (path.length > 1 && path.endsWith("/")) {
      path = path.slice(0, -1);
    }

    const upstreamUrl = FEEDS[path];
    if (!upstreamUrl) {
      return notFound();
    }

    // Cache key is the allowlisted path only. Query strings are never used.
    const cache = caches.default;
    const cacheKey = new Request(
      `https://androidnews-feed-proxy.internal${path}`,
      { method: "GET" },
    );
    const cached = await cache.match(cacheKey);
    if (cached) {
      return cached;
    }

    let upstream;
    try {
      upstream = await fetch(upstreamUrl, {
        method: "GET",
        headers: {
          "User-Agent": UPSTREAM_UA,
          Accept: UPSTREAM_ACCEPT,
        },
        cf: {
          cacheTtl: CACHE_TTL_SECONDS,
          cacheEverything: true,
          cacheTtlByStatus: {
            "200-299": CACHE_TTL_SECONDS,
            "400-499": 0,
            "500-599": 0,
          },
        },
      });
    } catch {
      return badGateway("upstream fetch failed");
    }

    const contentType =
      upstream.headers.get("content-type") || "application/xml; charset=utf-8";
    const response = new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: {
        "content-type": contentType,
        "cache-control": `public, max-age=${CACHE_TTL_SECONDS}`,
      },
    });

    if (upstream.ok) {
      ctx.waitUntil(cache.put(cacheKey, response.clone()));
    }
    return response;
  },
};

function notFound() {
  return new Response("Not found", {
    status: 404,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}

function badGateway(message) {
  return new Response(message, {
    status: 502,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}
