# GitHub setup

1. Sign in to GitHub and open your `options-bot` repository.
2. Authenticate local Git through GitHub CLI (`gh auth login`) or GitHub Desktop.
   Do not put a token in the remote URL. Use a clean URL such as
   `https://github.com/mehpackers13/options-bot.git`.
3. Under **Settings → Secrets and variables → Actions**, configure:
   - `DISCORD_WEBHOOK_URL` for alerts (optional)
   - `DISCORD_HEALTH_WEBHOOK_URL` for health and report messages (optional)
   - `TRADIER_API_TOKEN` for Tradier data (optional)
   - `ANTHROPIC_API_KEY` for AI reports (optional; API usage can incur costs)
4. Review and push the updated code. The test workflow runs on pushes and pull requests.
5. Enable Actions. Available operational workflows are Options Scan, Morning
   Self-Improvement, Weekly Report, and Deploy Dashboard to GitHub Pages.
6. To publish the dashboard, configure **Settings → Pages → Source → GitHub Actions**.
   Check your account's Pages availability and intended visibility first. Repository
   privacy alone is not a guarantee that a published dashboard is private.
7. Run a workflow manually only when ready to send its configured Discord messages.
   A scan outside market hours will skip scanning.

## Credentials previously embedded in files

Revoke the old GitHub personal access token under your GitHub developer settings.
Replace the exposed Discord webhook in Discord and update the corresponding
repository secret and local environment. Removing a secret from the latest source
file does not remove it from Git history or copies of the project.

## Troubleshooting

- Missing module: activate your Python 3.11+ environment and install `requirements.txt`.
- No alerts: inspect `bot.log`; five prior baseline days and all signal filters are required.
- Repeated tuning: inspect the `_ratings_fingerprint` in `data/thresholds.json`.
- Dashboard stale: inspect both the producing workflow and the Pages workflow.
- Push rejected: inspect concurrent human edits; do not force-push over newer data.
- AI unavailable: check the API secret, account access, and configured model.
