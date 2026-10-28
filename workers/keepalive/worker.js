export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(pingTarget(env));
  },
  async fetch(request, env, ctx) {
    const res = await pingTarget(env);
    return new Response(JSON.stringify(res), {
      headers: { "Content-Type": "application/json" },
      status: res.ok ? 200 : 500,
    });
  },
};

async function pingTarget(env) {
  const targetUrl = env.TARGET_URL;
  if (!targetUrl) {
    return {
      ok: false,
      error: "TARGET_URL environment variable is not configured.",
      timestamp: new Date().toISOString(),
    };
  }

  const url = targetUrl.endsWith("/health")
    ? targetUrl
    : `${targetUrl.replace(/\/+$/, "")}/health`;

  try {
    const response = await fetch(url, {
      method: "GET",
      headers: { "User-Agent": "Sylus-KeepAlive-Worker/1.0" },
    });
    return {
      ok: response.ok,
      status: response.status,
      url,
      timestamp: new Date().toISOString(),
    };
  } catch (err) {
    return {
      ok: false,
      error: err.message || String(err),
      url,
      timestamp: new Date().toISOString(),
    };
  }
}
