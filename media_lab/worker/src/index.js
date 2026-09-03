const CONTROL_QUERY_KEYS = new Set([
  "force_primary_failure",
  "origin",
]);

function corsHeaders() {
  return {
    "Access-Control-Allow-Headers": "Range, If-None-Match, If-Modified-Since",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Origin": "*",
  };
}

function responseWithMediaHeaders(response, origin, fallback) {
  const headers = new Headers(response.headers);
  for (const [name, value] of Object.entries(corsHeaders())) {
    headers.set(name, value);
  }
  headers.set("X-Media-Lab-Origin", origin);
  headers.set("X-Media-Lab-Fallback", String(fallback));
  return new Response(response.body, {
    headers,
    status: response.status,
    statusText: response.statusText,
  });
}

function upstreamUrl(baseOrigin, pathname, searchParams) {
  const target = new URL(`${baseOrigin.replace(/\/$/, "")}/${pathname}`);
  for (const [key, value] of searchParams) {
    if (!CONTROL_QUERY_KEYS.has(key)) {
      target.searchParams.append(key, value);
    }
  }
  return target;
}

function requestHeaders(request) {
  const headers = new Headers();
  for (const name of ["accept", "range", "if-none-match", "if-modified-since"]) {
    const value = request.headers.get(name);
    if (value) {
      headers.set(name, value);
    }
  }
  return headers;
}

async function fetchOrigin(request, baseOrigin, pathname, searchParams) {
  const target = upstreamUrl(baseOrigin, pathname, searchParams);
  try {
    const response = await fetch(target, {
      method: request.method,
      headers: requestHeaders(request),
      cf: {
        cacheEverything: true,
        cacheTtlByStatus: {
          "200-299": 300,
          "404": 2,
          "500-599": 0,
        },
      },
    });
    return { response, error: null };
  } catch (error) {
    return {
      response: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

function jsonResponse(payload, status) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      ...corsHeaders(),
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    const requestUrl = new URL(request.url);
    if (requestUrl.pathname === "/healthz") {
      return jsonResponse({ service: "robot-media-lab", status: "ok" }, 200);
    }

    const pathname = requestUrl.pathname.replace(/^\/+/, "") || "media/index.m3u8";
    if (!pathname.startsWith("media/")) {
      return jsonResponse({ error: "only /media/* is exposed by this lab" }, 404);
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return jsonResponse({ error: "method not allowed" }, 405);
    }
    if (!env.PRIMARY_ORIGIN || !env.FALLBACK_ORIGIN) {
      return jsonResponse({ error: "media origins are not configured" }, 500);
    }

    const forcePrimaryFailure = requestUrl.searchParams.get("force_primary_failure") === "1";
    const forceFallback = requestUrl.searchParams.get("origin") === "fallback";
    const primaryOrigin = forcePrimaryFailure
      ? "https://media-lab-primary-failure.invalid"
      : env.PRIMARY_ORIGIN;

    if (!forceFallback) {
      const primary = await fetchOrigin(
        request,
        primaryOrigin,
        pathname,
        requestUrl.searchParams,
      );
      if (primary.response?.ok) {
        return responseWithMediaHeaders(primary.response, "cloudfront-primary", false);
      }
    }

    const fallback = await fetchOrigin(
      request,
      env.FALLBACK_ORIGIN,
      pathname,
      requestUrl.searchParams,
    );
    if (fallback.response?.ok) {
      return responseWithMediaHeaders(fallback.response, "cloudfront-secondary", true);
    }

    return jsonResponse(
      {
        error: "both media origins failed",
        path: `/${pathname}`,
        primary_failure_injected: forcePrimaryFailure,
        fallback_status: fallback.response?.status ?? null,
      },
      502,
    );
  },
};
