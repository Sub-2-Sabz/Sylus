# Sylus Keep-Alive Cloudflare Worker

This directory contains a Cloudflare Worker that keeps the Sylus Render web service awake by sending periodic HTTP `GET /health` requests every 5 minutes.

## Files
- `worker.js`: Cloudflare Worker source script handling cron scheduled events (`scheduled`) and manual HTTP requests (`fetch`).
- `wrangler.jsonc`: Wrangler CLI configuration specifying cron schedules (`*/5 * * * *`) and environment variable bindings.

## Deployment Options

### Option A: Cloudflare Dashboard (Mobile/Phone-Friendly)
1. Log into your [Cloudflare Dashboard](https://dash.cloudflare.com/).
2. Navigate to **Workers & Pages** -> **Overview** and click **Create Application**.
3. Click **Create Worker**, name it `sylus-keepalive`, and click **Deploy**.
4. Click **Edit code** in the top right.
5. Paste the contents of `worker.js` into the online editor and click **Save and Deploy**.
6. Go to Worker **Settings** -> **Variables**, add an Environment Variable `TARGET_URL` with your Render URL (e.g. `https://sylus.onrender.com`).
7. Go to Worker **Settings** -> **Triggers** -> **Cron Triggers**, and add `*/5 * * * *` (Every 5 minutes).

### Option B: Wrangler CLI
1. Install Wrangler CLI:
   ```bash
   npm install -g wrangler
   ```
2. Authenticate with Cloudflare:
   ```bash
   npx wrangler login
   ```
3. Deploy worker:
   ```bash
   npx wrangler deploy
   ```
4. Set secret variable:
   ```bash
   npx wrangler secret put TARGET_URL
   ```
