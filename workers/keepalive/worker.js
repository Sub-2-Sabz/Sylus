// In-memory state for tracking consecutive failures
let consecutiveFailures = 0;

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(pingTarget(env));
  },
  async fetch(request, env, ctx) {
    const res = await pingTarget(env);
    return new Response(`Sylus Keep-Alive status: ${res.ok ? "OK" : "FAIL"} (${res.status || res.error})`, {
      headers: { "Content-Type": "text/plain" },
      status: res.ok ? 200 : 500,
    });
  },
};

async function pingTarget(env) {
  const healthUrl = env.HEALTH_URL || env.TARGET_URL;
  if (!healthUrl) {
    console.error("HEALTH_URL environment variable is not configured.");
    return {
      ok: false,
      error: "HEALTH_URL environment variable is not configured.",
      timestamp: new Date().toISOString(),
    };
  }

  const url = healthUrl.endsWith("/health")
    ? healthUrl
    : `${healthUrl.replace(/\/+$/, "")}/health`;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30000); // 30 second timeout

  try {
    const response = await fetch(url, {
      method: "GET",
      headers: { "User-Agent": "sylus-keepalive" },
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    console.log(`Ping to ${url} returned HTTP ${response.status}`);

    if (response.ok) {
      consecutiveFailures = 0;
      return {
        ok: true,
        status: response.status,
        url,
        timestamp: new Date().toISOString(),
      };
    } else {
      consecutiveFailures++;
      console.warn(`Ping failed. Consecutive failures: ${consecutiveFailures}`);
      if (consecutiveFailures >= 2 && env.ALERT_WEBHOOK_URL) {
        await sendWebhookAlert(env.ALERT_WEBHOOK_URL, url, `HTTP ${response.status}`);
      }
      return {
        ok: false,
        status: response.status,
        url,
        timestamp: new Date().toISOString(),
      };
    }
  } catch (err) {
    clearTimeout(timeoutId);
    consecutiveFailures++;
    console.error(`Ping error: ${err.message || String(err)}. Consecutive failures: ${consecutiveFailures}`);
    if (consecutiveFailures >= 2 && env.ALERT_WEBHOOK_URL) {
      await sendWebhookAlert(env.ALERT_WEBHOOK_URL, url, err.message || String(err));
    }
    return {
      ok: false,
      error: err.message || String(err),
      url,
      timestamp: new Date().toISOString(),
    };
  }
}

async function sendWebhookAlert(webhookUrl, targetUrl, reason) {
  try {
    await fetch(webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content: `🚨 **Sylus Keep-Alive Alert**: Health check at \`${targetUrl}\` failed twice in a row! Reason: ${reason}`,
      }),
    });
  } catch (e) {
    console.error("Failed to post alert to ALERT_WEBHOOK_URL", e);
  }
}
