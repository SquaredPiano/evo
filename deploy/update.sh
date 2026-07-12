#!/usr/bin/env bash
# Evo auto-deploy - pull the latest `main` and rebuild ONLY when it changed.
#
# Safe to run on a timer (cron/systemd). Properties:
#   * No change  -> exits fast, no rebuild, no downtime.
#   * A failed build leaves the running app untouched (compose builds the new
#     images before recreating containers; if the build fails it aborts).
#   * .env is gitignored, so `git reset --hard` preserves your secrets.
#
# Install on the droplet (runs every 5 min, logs to /var/log/evo-update.log):
#   chmod +x /root/evo/deploy/update.sh
#   ( crontab -l 2>/dev/null; echo "*/5 * * * * /root/evo/deploy/update.sh >> /var/log/evo-update.log 2>&1" ) | crontab -
#
# Manual one-off update:
#   /root/evo/deploy/update.sh

set -uo pipefail

REPO_DIR="${EVO_DIR:-/root/evo}"
cd "$REPO_DIR" || { echo "$(date -u) ERROR: $REPO_DIR not found"; exit 1; }

git fetch origin main --quiet || { echo "$(date -u) ERROR: git fetch failed"; exit 1; }

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
	echo "$(date -u) up-to-date (${LOCAL:0:7})"
	exit 0
fi

echo "$(date -u) change detected ${LOCAL:0:7} -> ${REMOTE:0:7}; redeploying"
git reset --hard origin/main
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker image prune -f >/dev/null 2>&1 || true
echo "$(date -u) redeploy complete (${REMOTE:0:7})"
