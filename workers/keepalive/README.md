# Sylus Keep-Alive Cloudflare Worker

This directory contains a Cloudflare Worker that keeps the Sylus Render web service awake by sending periodic HTTP `GET /health` requests every 5 minutes.

## Files
- `worker.js`: Cloudflare Worker source script handling cron scheduled events (`scheduled`) and manual HTTP requests (`fetch`).
- `wrangler.jsonc`: Wrangler CLI configuration specifying cron schedules (`2-59/5 * * * *`) and environment variable bindings (`HEALTH_URL`).

## Deployment Options

### Method 1: Cloudflare Dashboard (Mobile / Phone-Friendly Method)
1. Log into your [Cloudflare Dashboard](https://dash.cloudflare.com/).
2. Navigate to **Workers & Pages** -> **Overview** and click **Create Application**.
3. Click **Create Worker**, name it `sylus-keepalive`, and click **Deploy**.
4. Click **Edit code** in the top right.
5. Paste the contents of `worker.js` into the online editor and click **Save and Deploy**.
6. Go to Worker **Settings** -> **Variables**, add an Environment Variable `HEALTH_URL` with your Render health check URL (e.g., `https://sylus.onrender.com/health`). Optionably add `ALERT_WEBHOOK_URL` with a Discord webhook URL to receive alerts after 2 consecutive failures.
7. Go to Worker **Settings** -> **Triggers** -> **Cron Triggers**, and add `2-59/5 * * * *` (Every 5 minutes, offset by 2 minutes).
8. Open the Worker's public URL in your browser once to verify it responds with a short status message (`Sylus Keep-Alive status: OK`).

### Method 2: GitHub Method (Optional)
1. In Cloudflare Dashboard, go to **Workers & Pages** -> **Create Application** -> **Pages / Workers Git Integration**.
2. Connect your GitHub repository (`sylus`) and select the `workers/keepalive` folder as the root directory.
3. Configure environment variable `HEALTH_URL` in the Cloudflare deployment settings.
