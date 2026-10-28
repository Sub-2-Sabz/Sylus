# Sylus - Grand Strategy Discord Bot Platform

Sylus is a grand strategy bot platform integrated with Discord, built with Python 3.12, Py-cord, async SQLAlchemy, Alembic, aiohttp, and structlog.

---

## Phone-Friendly Copy-Paste Deployment Setup Guide

Follow this step-by-step guide to set up and deploy Sylus completely for free on smartphone or desktop.

### Step 1: GitHub Repository Setup
1. Fork or push this repository to your GitHub account.
2. Note your repository URL: `https://github.com/YOUR_USERNAME/sylus`

### Step 2: Discord Bot Creation
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Tap **New Application**, enter `Sylus`, and create it.
3. Select **Bot** from the side menu.
4. Tap **Reset Token** and copy your token (Save as `DISCORD_TOKEN`).
5. Under **Privileged Gateway Intents**, enable:
   - **Message Content Intent**
   - **Server Members Intent**
6. Go to **OAuth2** -> **URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Read Message History`
7. Copy the generated URL and open it in a browser to invite Sylus to your Discord server.

### Step 3: Neon PostgreSQL Database Setup
1. Go to [Neon.tech](https://neon.tech/) and sign up for a free account.
2. Create a new project named `sylus-db`.
3. In the Dashboard, copy the connection string.
4. Replace `postgresql://` with `postgresql+asyncpg://` for async SQLAlchemy compatibility:
   ```text
   postgresql+asyncpg://user:password@ep-cool-site.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
5. Save this as `DATABASE_URL`.

### Step 4: Render Deployment
1. Go to [Render.com](https://render.com/) and log in.
2. Tap **New +** -> **Blueprint**.
3. Connect your GitHub repository (`sylus`).
4. Render will automatically detect `render.yaml`.
5. Set the required Environment Variables in Render:
   - `DATABASE_URL`: *(Your Neon connection string from Step 3)*
   - `DISCORD_TOKEN`: *(Your Discord bot token from Step 2)*
   - `INTERNAL_SECRET`: *(A random secret string for triggering internal turn execution)*
6. Tap **Apply**. Render will build the Docker container, launch the web server on `/health`, run database migrations, and start the Discord bot.
7. Copy your deployed app URL (e.g., `https://sylus.onrender.com`).

### Step 5: Cloudflare Worker Keep-Alive Setup (Dashboard Method)
To prevent Render's free tier from spinning down after 15 minutes of inactivity:
1. Log into [Cloudflare Dashboard](https://dash.cloudflare.com/).
2. Tap **Workers & Pages** -> **Create Application** -> **Create Worker**.
3. Name it `sylus-keepalive` and tap **Deploy**.
4. Tap **Edit Code**. Paste the code from `workers/keepalive/worker.js`.
5. Tap **Save and Deploy**.
6. Tap **Settings** -> **Variables**, add environment variables:
   - `HEALTH_URL`: `https://sylus.onrender.com/health`
   - `ALERT_WEBHOOK_URL`: *(Optional Discord webhook URL to receive failure alerts)*
7. Tap **Settings** -> **Triggers** -> **Add Cron Trigger**:
   - Cron Expression: `2-59/5 * * * *` (Every 5 minutes, offset by 2 minutes from UptimeRobot)
8. Open the Worker URL in your browser to confirm it returns `Sylus Keep-Alive status: OK`.

### Step 6: UptimeRobot Backup Monitoring
1. Go to [UptimeRobot](https://uptimerobot.com/).
2. Tap **Add New Monitor**:
   - Monitor Type: `HTTP(s)`
   - Friendly Name: `Sylus Health Check`
   - URL: `https://sylus.onrender.com/health`
   - Monitoring Interval: `5 minutes`
3. Tap **Create Monitor**.

---

## Troubleshooting Guide (Section 15.6)

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| **Bot appears offline on Discord** | Invalid token or missing Gateway Intents. | Double-check `DISCORD_TOKEN` in Render environment variables. Ensure **Message Content Intent** is enabled in Discord Developer Portal. |
| **Render Web Service sleeping** | Inactivity timeout on free tier (15 mins). | Verify Cloudflare Worker Cron trigger (`2-59/5 * * * *`) and UptimeRobot monitor pointing to `https://<app>.onrender.com/health`. |
| **Database Connection Errors** | Missing `asyncpg` driver prefix or wrong URI format. | Ensure `DATABASE_URL` starts with `postgresql+asyncpg://` instead of `postgresql://`. |
| **Database Migrations Fail on Startup** | Unreachable database or pending locking transaction. | Check Neon project status and confirm database connection details. Review service startup logs on Render dashboard. |
| **Port / Address Already in Use** | Port conflict during local startup or container startup. | Sylus reads `PORT` or `HTTP_PORT` dynamically. Ensure `PORT=8080` is exposed properly in Docker. |
| **Discord Bot Disconnecting Repeatedly** | Temporary Discord API network outage or rate limit. | Sylus handles automatic reconnects with exponential backoff (`reconnect_initial_backoff: 5s` up to `300s`). |

---

## Expected Costs & Hosting Limits (Section 15.6)

- **Total Expected Monthly Cost:** **$0.00**
- **Render Free Tier:** 750 free instance hours/month, spins down after 15 mins of HTTP inactivity, ephemeral disk. Keep-alive pings keep it awake.
- **Neon Free Tier:** 0.5 GiB storage, 190 compute hours/month, scales to zero when idle. Using `NullPool` prevents unneeded DB connections.
- **Cloudflare Workers:** 100,000 requests/day free allowance.
- **Discord Attachments:** Maximum 10 MB per file limit for backup snapshots and map images.

### Upgrade Path
If the free setup ever becomes unreliable or hits compute limits as player count grows, moving to an always-on VPS (e.g. $5/month Hetzner or DigitalOcean droplet) only requires pointing the Docker image to the new host. No code changes are required because game logic does not depend on keep-alive pings to operate correctly.

---

## Local Development & Testing

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run test suite:
   ```bash
   python3 -m pytest
   ```
3. Run Sylus application:
   ```bash
   python -m sylus.main
   ```
