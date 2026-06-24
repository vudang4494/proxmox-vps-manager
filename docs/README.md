# Bộ tài liệu — Hệ thống tạo VPS trên Proxmox

Tài liệu mô tả **toàn bộ hệ thống hiện có** để tự động tạo/quản lý VPS (KVM) trên Proxmox,
gồm 3 tầng: **Web panel (Node.js)** → **API service (FastAPI)** → **Proxmox VE**.

## Mục lục

| # | Tài liệu | Nội dung |
|---|---|---|
| 01 | [Kiến trúc tổng quan](01-kien-truc.md) | Sơ đồ 3 tầng, luồng xử lý, thành phần, công nghệ |
| 02 | [Cài đặt & triển khai](02-trien-khai.md) | Dựng từ đầu: template, FastAPI, web panel, file cấu hình |
| 03 | [Vận hành & sử dụng](03-van-hanh.md) | Chạy/dừng, SSH tunnel, systemd, tạo VPS, log, troubleshooting |
| 04 | [Bảo mật](04-bao-mat.md) | Credentials, firewall, bề mặt tấn công, khuyến nghị |
| — | [API Reference](../API_GUIDE.md) | Chi tiết từng endpoint REST (đã có sẵn) |
| — | [README dự án](../README.md) | Giới thiệu nhanh + chuẩn bị Proxmox |

## Quickstart (30 giây)

Sau khi đã dựng theo docs/02, để dùng ngay:

```bash
# 1) Mở SSH tunnel tới FastAPI (8000) + Shell Console Proxmox (8006) — giữ terminal mở
ssh -p 22 -N -L 8000:127.0.0.1:8000 -L 8006:127.0.0.1:8006 root@YOUR_PROXMOX_HOST &

# 2) Chạy web panel bằng PM2 (process tên 'cloudproxmox')
cd ~/proxmox-vps-manager/web && pm2 start server.js --name cloudproxmox
#    (hoặc trực tiếp: npm start)

# 3) Mở trình duyệt rồi đăng nhập (PANEL_USER / mật khẩu trong web/.env)
open http://localhost:9999
```

Hoặc gọi thẳng API bằng curl — xem [API Reference](../API_GUIDE.md).

## Thông tin nhanh

| Hạng mục | Giá trị |
|---|---|
| Server Proxmox | `pve` — `YOUR_PROXMOX_HOST` (SSH cổng `22`) |
| Phiên bản | Proxmox VE 8.x/9.x · Debian 12/13 (điền theo môi trường của bạn) |
| Template clone | VMID `9000` (`ubuntu-2404-tpl`, Ubuntu 24.04 + cloud-init) |
| FastAPI service | `/opt/proxmox-vps-api` · systemd `proxmox-vps-api` · `127.0.0.1:8000` |
| Web panel | `web/` (Node.js/Express) · port `9999` · **có đăng nhập** (PM2 `cloudproxmox`) |
| Tính năng web | Tạo VPS (User/Pass riêng mỗi VPS, sudo) · **Shell Console** (xterm.js) · Chi tiết VM |
| Credentials | file `Key` + các `.env` (gitignored) — xem [Bảo mật](04-bao-mat.md) |
