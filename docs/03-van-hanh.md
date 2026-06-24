# 03 — Vận hành & sử dụng

## Khởi động hệ thống

FastAPI (trên server) chạy bằng systemd nên **tự bật khi server boot**. Chỉ cần lo 2 thứ
ở máy dev: SSH tunnel + web panel.

```bash
# 1) Tunnel tới FastAPI (8000) + Shell Console Proxmox (8006) — giữ chạy nền
ssh -p 22 -N -L 8000:127.0.0.1:8000 -L 8006:127.0.0.1:8006 root@YOUR_PROXMOX_HOST &

# 2) Web panel (PM2 — process tên 'cloudproxmox')
cd ~/proxmox-vps-manager/web && pm2 start server.js --name cloudproxmox
#   (hoặc chạy trực tiếp: npm start)

# 3) Mở http://localhost:9999  → đăng nhập (PANEL_USER / mật khẩu)
```

> **Đăng nhập:** web `:9999` có trang login (session). Tài khoản đặt trong `web/.env`
> (`PANEL_USER`, `PANEL_PASS_HASH`). Chưa đăng nhập → mọi trang redirect về `/login`.

Kiểm tra nhanh các tầng đang sống:

```bash
curl http://localhost:8000/health        # FastAPI (qua tunnel) -> {"status":"ok",...}
curl http://localhost:9999/api/options   # Web panel -> presets
```

## Quản lý FastAPI service (systemd, trên server)

```bash
ssh -p 22 root@YOUR_PROXMOX_HOST            # vào server

systemctl status  proxmox-vps-api         # trạng thái
systemctl restart proxmox-vps-api         # khởi động lại (vd sau khi sửa .env)
systemctl stop    proxmox-vps-api         # dừng
journalctl -u proxmox-vps-api -f          # log realtime
```

Cập nhật code FastAPI: `rsync` lại lên `/opt/proxmox-vps-api/` rồi `systemctl restart proxmox-vps-api`.

## Quản lý Web panel (PM2)

Web panel chạy dưới **PM2** với process tên **`cloudproxmox`**:

```bash
pm2 status                 # trạng thái
pm2 logs cloudproxmox      # log realtime
pm2 restart cloudproxmox   # restart (vd sau khi sửa web/.env hoặc code)
pm2 stop cloudproxmox      # dừng
pm2 save                   # lưu để PM2 resurrect sau khi khởi động lại
```

> PM2 chỉ quản lý tiến trình Node — **không** quản lý SSH tunnel (vẫn phải mở tay).
> Chạy trực tiếp không qua PM2: `cd web && npm start`.

## Tạo VPS

### Cách 1 — Giao diện web (khuyến nghị)

Mở `http://localhost:9999` (đăng nhập trước):
1. Nhập **Tên VPS** (chữ/số/`-`).
2. Chọn **CPU** (4/8/16), **RAM** (4/8/16/24/32/64 GB), **SSD** (100/200/300 GB).
3. Đặt **User** + **Mật khẩu** đăng nhập VPS (trường chính, có nút 🎲 tạo ngẫu nhiên).
   Mỗi VPS một user/pass **riêng**, có **toàn quyền sudo**, độc lập user Proxmox.
4. Bấm **Tạo VPS** → kết quả (VMID, trạng thái) + **User/Pass** hiện ngay; bảng dưới cập nhật.

Network để trống = **DHCP** (gán IP WAN tĩnh sẽ thiết kế sau).

### Cách 2 — Gọi API trực tiếp

Xem chi tiết tham số ở [API Reference](../API_GUIDE.md). Ví dụ:

```bash
APIKEY=$(grep '^API_KEY=' ~/proxmox-vps-manager/Key | cut -d= -f2)
curl -X POST http://localhost:8000/api/v1/vps \
  -H "Content-Type: application/json" -H "X-API-Key: $APIKEY" \
  -d '{"name":"vps-01","cores":8,"memory_mb":16384,"disk_gb":100}'
```

## Liệt kê / Xoá VPS

- **Web:** bảng "VPS hiện có" — mỗi dòng có nút **ℹ︎ Chi tiết** (cấu hình disk/IP/bridge), **⌨ Console** (Shell xterm.js mở thẳng trên trình duyệt) và **Xoá** (template 9000 bị khoá); nút **Làm mới** ở góc.
- **API:** `GET /api/v1/vps`, `DELETE /api/v1/vps/{vmid}` (xem API Reference).
- **Trên Proxmox:** `qm list`, `qm status <vmid>`, `qm config <vmid>`.

## Troubleshooting

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| Web `:9999` mở được nhưng tạo VPS lỗi "Không gọi được Proxmox API" | SSH tunnel chưa mở / đã rớt | Mở lại tunnel cổng 8000 |
| Bấm **⌨ Console** không kết nối được | Tunnel thiếu cổng **8006** | Mở tunnel có cả `-L 8006:127.0.0.1:8006` |
| Vào web bị đẩy về trang đăng nhập | Chưa login / hết phiên | Đăng nhập lại bằng `PANEL_USER` trong `web/.env` |
| `curl localhost:8000/health` lỗi connection | Tunnel chưa mở, hoặc FastAPI dừng | Mở tunnel; `systemctl status proxmox-vps-api` |
| Web báo `401` | `API_KEY` trong `web/.env` ≠ `.env` của FastAPI | Đồng bộ 2 key, restart web |
| Tạo VPS `400` "Clone template thất bại" | Template 9000 không có / sai | `qm list` kiểm tra template 9000 |
| Tạo VPS `400` resize | `disk_gb` nhỏ hơn disk template | Chọn SSD ≥ kích thước template |
| Web `400` "CPU phải thuộc..." | Gửi giá trị ngoài preset | Chỉ chọn trong dropdown |
| Bảng VPS trống/timeout | FastAPI hoặc Proxmox không phản hồi | Kiểm tra service + `pveproxy` |

Mã lỗi đầy đủ (200/201/204/400/401/404/422/502/503/504): [API Reference §6](../API_GUIDE.md).

## File log

| Thành phần | Log |
|---|---|
| FastAPI | `journalctl -u proxmox-vps-api` (trên server) |
| Web panel | stdout (hoặc file bạn redirect, vd `/tmp/vps-web.log`) |
| Proxmox task | UI Proxmox, hoặc `/var/log/pve/tasks/` |
