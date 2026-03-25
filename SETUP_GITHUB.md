# How to Put Your Bot on GitHub (Complete Beginner Guide)

This takes about 10 minutes. Once done, your bot runs automatically in the cloud —
**your Mac never needs to be on.**

---

## What is GitHub?
GitHub is a free website that stores your code and can run it automatically on a schedule.
Think of it like a combination of Dropbox (for code) and a timer (that runs your bot).

---

## Step 1 — Create a Free GitHub Account

1. Go to **https://github.com** and click **Sign up**
2. Enter your email, create a password, and pick a username
3. Verify your email address
4. On the "What kind of work do you do?" screen, just click **Skip personalization**

---

## Step 2 — Create a New Repository (your bot's home on GitHub)

1. Once logged in, click the **+** button in the top-right corner
2. Click **New repository**
3. Fill in:
   - **Repository name:** `options-bot`
   - **Description:** `Self-improving options alert bot`
   - **Visibility:** ✅ Private (keeps your webhook URLs safe)
   - Leave everything else unchecked
4. Click **Create repository**
5. You'll land on a page with setup instructions — **leave this tab open**

---

## Step 3 — Install Git on Your Mac (if not already installed)

1. Open **Terminal** (press Cmd+Space, type "Terminal", press Enter)
2. Type this and press Enter:
   ```
   git --version
   ```
3. If you see a version number (e.g. `git version 2.39.0`), you're good — skip to Step 4.
4. If a popup appears asking to install Xcode Command Line Tools, click **Install** and wait.

---

## Step 4 — Push Your Bot to GitHub

Copy and paste these commands into Terminal **one at a time**, pressing Enter after each.

Replace `YOUR-USERNAME` with your actual GitHub username (the one you just created).

```bash
cd ~/Desktop/options-bot
```
```bash
git init
```
```bash
git add .
```
```bash
git commit -m "Initial commit — options alert bot"
```
```bash
git branch -M main
```
```bash
git remote add origin https://github.com/YOUR-USERNAME/options-bot.git
```
```bash
git push -u origin main
```

When prompted for a username/password:
- **Username:** your GitHub username
- **Password:** use a Personal Access Token (see below)

### Getting a Personal Access Token (replaces your password)
1. Go to **https://github.com/settings/tokens**
2. Click **Generate new token → Generate new token (classic)**
3. Give it a name like "options-bot"
4. Set **Expiration** to "No expiration"
5. Check the box next to **repo** (full control of private repositories)
6. Scroll down and click **Generate token**
7. **Copy the token immediately** — GitHub will never show it again
8. Use this token as your password when Terminal asks

---

## Step 5 — Add Your Discord Webhook URLs as Secrets

This keeps your webhook URLs private and makes them available to GitHub Actions.

1. On your GitHub repository page, click **Settings** (top tab)
2. In the left sidebar, click **Secrets and variables → Actions**
3. Click **New repository secret** and add these one at a time:

| Secret name                  | Value                                      |
|------------------------------|--------------------------------------------|
| `DISCORD_WEBHOOK_URL`        | Your signals channel webhook URL           |
| `DISCORD_HEALTH_WEBHOOK_URL` | Your health channel webhook URL (optional) |

To add each one:
- Click **New repository secret**
- Type the exact name from the table above
- Paste your webhook URL
- Click **Add secret**

---

## Step 6 — Enable GitHub Pages (your live dashboard)

1. On your repository page, click **Settings**
2. In the left sidebar, scroll down to **Pages**
3. Under **Source**, select **GitHub Actions** from the dropdown
4. Click **Save**

The dashboard will be live at:
```
https://YOUR-USERNAME.github.io/options-bot/
```

After your first push, GitHub will automatically build and publish it within 2–3 minutes.

---

## Step 7 — Enable GitHub Actions (the bot's scheduler)

1. On your repository page, click the **Actions** tab
2. If you see a yellow banner asking "I understand my workflows", click that button
3. You should see three workflows listed:
   - **Options Scan** — runs every 15 min during market hours
   - **Morning Self-Improvement** — runs at 8am ET weekdays
   - **Deploy Dashboard to GitHub Pages** — updates your dashboard

4. To test it right now: click **Options Scan** → click **Run workflow** → click the green **Run workflow** button

---

## Step 8 — Set Up Two Discord Channels (5 minutes)

### Create the channels:
1. In Discord, right-click your server name → **Edit Server**
2. Go to **Channels** → click **+** to add a channel
3. Name it `#options-signals` (for trade alerts)
4. Add another channel named `#bot-health` (for scan summaries)

### Create webhooks for each:
For each channel:
1. Click the gear icon next to the channel name
2. Go to **Integrations → Webhooks**
3. Click **New Webhook**
4. Give it a name (e.g. "Options Bot")
5. Click **Copy Webhook URL**
6. Paste that URL into the matching GitHub Secret (Step 5 above)

---

## You're Done! Here's What Happens Automatically:

| Time (ET)          | What runs                                           |
|--------------------|-----------------------------------------------------|
| 8:00 AM weekdays   | Self-improvement analysis (once 20+ alerts rated)   |
| 9:30 AM – 4:00 PM  | Bot scans your 5 tickers every 15 minutes           |
| Any signal found   | Discord alert → #options-signals                    |
| Each scan complete | Health update → #bot-health                         |
| After each scan    | Dashboard at github.io updates automatically        |

---

## How to Rate Alerts (to activate self-improvement)

1. Go to your repository on GitHub
2. Click on `alerts_log.csv`
3. Click the pencil icon to edit it
4. In the `outcome` column, type:
   - `1` if the signal was correct (price moved as expected)
   - `0` if it was a false alarm
5. Click **Commit changes**

Once you've rated 20+ alerts, the bot will automatically tune its own thresholds
each morning to improve accuracy. Every change it makes is logged in `threshold_changes.log`.

---

## Troubleshooting

**"Permission denied" when pushing to GitHub**
→ Make sure you're using your Personal Access Token as the password, not your GitHub password.

**Workflows aren't running**
→ Go to Actions tab → make sure workflows are enabled → try "Run workflow" manually.

**Dashboard shows "No data"**
→ Wait for the first scan to complete (happens at next 15-min mark during market hours).
   You can also trigger it manually from the Actions tab.

**Bot finds no signals**
→ Normal! The default thresholds are conservative. Check `bot.log` in your repo
   to confirm scans are running.
