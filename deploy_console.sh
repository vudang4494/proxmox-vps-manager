#!/usr/bin/env bash
# Deploy tính năng Shell Console + chi tiết VM (giữ nguyên kiến trúc đang chạy).
# Console dùng API TOKEN (đã kiểm chứng chạy trên PVE 9.2) — KHÔNG cần root password.
# Idempotent. Dùng:  bash deploy_console.sh
set -euo pipefail

LOCAL=~/proxmox-vps-manager
HOSTSSH="root@YOUR_PROXMOX_HOST"
SSH="ssh -p 22 -o ConnectTimeout=15 $HOSTSSH"

echo "==> [1/5] rsync app/ lên server"
rsync -az -e "ssh -p 22 -o ConnectTimeout=15" \
  --exclude='.venv' --exclude='__pycache__' --exclude='.env' --exclude='Key' \
  --exclude='node_modules' --exclude='*.log' --exclude='.DS_Store' \
  "$LOCAL/app/" "$HOSTSSH:/opt/proxmox-vps-api/app/"

echo "==> [2/5] restart FastAPI service + health"
$SSH "systemctl restart proxmox-vps-api; sleep 3; systemctl is-active proxmox-vps-api"

echo "==> [3/5] npm install (ws) cho web panel"
( cd "$LOCAL/web" && npm install --no-audit --no-fund )

echo "==> [4/5] restart SSH tunnel (forward 8000 + 8006 — 8006 cho console WS)"
pkill -f 'L 8000:127.0.0.1:8000' 2>/dev/null || true
sleep 1
nohup ssh -p 22 -o ServerAliveInterval=30 -N \
  -L 8000:127.0.0.1:8000 -L 8006:127.0.0.1:8006 "$HOSTSSH" >/tmp/vps-tunnel.log 2>&1 &
sleep 2

echo "==> [5/5] restart web panel (port 9999)"
pkill -f 'node.*server.js' 2>/dev/null || true
sleep 1
nohup bash -c "cd '$LOCAL/web' && npm start" >/tmp/vps-web.log 2>&1 &
sleep 2

echo ""
echo "✅ Xong. Kiểm tra:"
echo "   - FastAPI:  curl -s http://127.0.0.1:8000/health"
echo "   - Web:      http://localhost:9999"
echo "   - Console:  bấm '⌨ Console' ở 1 VM đang chạy"
