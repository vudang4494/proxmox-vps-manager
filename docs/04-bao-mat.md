# 04 — Bảo mật

## Kho credentials (ai giữ gì)

| Bí mật | Dùng để | Lưu ở đâu |
|---|---|---|
| **API_KEY** (X-API-Key) | Client gọi FastAPI | `Key`, `/opt/proxmox-vps-api/.env`, `web/.env` |
| **Proxmox token** `root@pam!automation` | FastAPI ↔ Proxmox | `/opt/proxmox-vps-api/.env` (trên server), `Key` (cục bộ dev) |
| **Đăng nhập web panel** (`PANEL_USER` / `PANEL_PASS_HASH`) | Đăng nhập UI `:9999` | `web/.env` — mật khẩu lưu **hash scrypt** (`salt:hash`), KHÔNG plaintext |
| **User/Pass mỗi VPS** (cloud-init) | Đăng nhập vào từng VPS (quyền sudo) | Sinh khi tạo VPS, hiện **1 lần** trên web; không lưu tập trung — **độc lập** token Proxmox |
| **SSH password root** | Đăng nhập server | `Key` (đã chuyển sang ưu tiên SSH key) |
| **SSH private key** | Đăng nhập server (chính) | `~/.ssh/id_ed25519` trên Mac |

> `Key` là **file text cục bộ (dev)** gom mọi bí mật để tra cứu — không phải `.env`. File `Key`, mọi
> `.env` (gồm `web/.env`) đều đã `.gitignore` — **không commit, không chia sẻ** (kiểm: `grep -E "^Key$|^\.env" .gitignore`).

## Các lớp xác thực

```
Trình duyệt ──(login session)──▶ Web panel ──(X-API-Key)──▶ FastAPI ──(API token)──▶ Proxmox
```

1. **Trình duyệt → Web panel:** ✅ **ĐÃ có đăng nhập** (session-based, `express-session`).
   Mọi route đều bị chặn trừ `/login`; chưa đăng nhập → trang web redirect `/login`, gọi `/api/*` → `401`.
   Tài khoản trong `web/.env`: `PANEL_USER` + `PANEL_PASS_HASH` (mật khẩu lưu **hash scrypt** `salt:hash`,
   không plaintext; so khớp **timing-safe**). Có nút Đăng xuất (`POST /logout`).
   ⚠️ **Chưa có rate-limit** ở tầng login — cần bổ sung trước khi phơi web ra mạng (xem khuyến nghị dưới).
2. **Web → FastAPI:** header `X-API-Key`. Sai/thiếu → `401`. Key là chuỗi ngẫu nhiên 64 hex.
   ⚠️ Nếu `API_KEY` để **rỗng** trong `.env` (vd `API_KEY=`), FastAPI **bỏ qua xác thực** — mọi request
   đều đi qua. Luôn đặt key mạnh (≥ 32 ký tự ngẫu nhiên).
   Lưu ý: endpoint `/health` **không** yêu cầu auth (cho monitoring) — chỉ lộ version, không lộ dữ liệu.
3. **FastAPI → Proxmox:** API token. Hiện token **toàn quyền** (privsep=0) — tiện test, kém an toàn.
4. **Shell Console (WebSocket):** trình duyệt **không** giữ token Proxmox. FastAPI cấp ticket termproxy
   (qua API token), Node giữ `Authorization: PVEAPIToken=...` phía server và chèn vào upgrade WS tới
   Proxmox `:8006`; browser chỉ nhận `wsToken` (cấp sau khi đã đăng nhập) + ticket ngắn hạn.
   *Phát hiện:* WebSocket Proxmox PVE 9.2 **chấp nhận API token** — không cần login-ticket; hướng
   login-ticket bằng mật khẩu thất bại vì `root@pam` bật **2FA**.

## Firewall (Proxmox firewall đang BẬT)

| Cổng | Quy tắc | Ghi chú |
|---|---|---|
| `22` (SSH) | Chỉ cho IP `YOUR_ADMIN_IP` | IP public của Mac — "chỉ Mac vào được" |
| `8006` (Proxmox web/API) | **Mở cho mọi nơi** | Bề mặt tấn công công khai |
| `80` / `443` | **Bị chặn** (default DROP) | Cần mở nếu dựng nginx |
| `8000` (FastAPI) | Chỉ `127.0.0.1` | Không ra ngoài; tới qua SSH tunnel |
| `9999` (Web) | Chỉ localhost Mac | Không ra ngoài; đã có đăng nhập (session) |

## Bề mặt tấn công hiện tại

- **Đang phơi ra internet:** chỉ cổng `8006` (Proxmox) và `22` (SSH, đã giới hạn IP).
- **FastAPI (8000) và Web (9999):** không reachable từ ngoài → rủi ro thấp ở giai đoạn này.
- Rủi ro lớn nhất khi mở rộng: phơi web/API ra mạng mà **chưa có rate-limit cho login web** + token Proxmox vẫn toàn quyền. (Đăng nhập web đã có; rate-limit thì chưa.)

## Khuyến nghị & việc cần làm

| Mức | Việc | Trạng thái |
|---|---|---|
| Cao | **Đăng nhập web panel** (session, mật khẩu hash scrypt) | ✅ đã làm |
| Cao | **Rate-limit** đăng nhập web panel (chống brute-force) trước khi phơi ra ngoài | ⬜ chưa làm |
| Cao | **Phân quyền Proxmox token**: đổi root toàn quyền → token privsep + role `PVEVMAdmin` | ⬜ chưa làm |
| Cao | **Hạn chế cổng 8006** (Proxmox web/API đang mở public) — giới hạn IP nguồn qua firewall | ⬜ chưa làm |
| TB | Dựng **nginx + Let's Encrypt (HTTPS)** cho endpoint domain (mở firewall 80/443) | ⬜ chưa làm |
| TB | Bật `PROXMOX_VERIFY_SSL=true` (hiện **False** — ổn vì trỏ localhost/self-signed; cần cert hợp lệ nếu nói chuyện Proxmox qua mạng) | ⬜ |
| TB | Thêm **rate-limit** khi mở API ra ngoài | ⬜ |
| Thấp | Xoay vòng `API_KEY`: cập nhật `/opt/proxmox-vps-api/.env` + `web/.env` + `Key` rồi **restart cả 2** (`systemctl restart proxmox-vps-api` và web) — dotenv chỉ nạp lúc khởi động | ⬜ |
| Thấp | Đổi/loại bỏ SSH password, chỉ dùng key | một phần (đã có key) |

## Nguyên tắc khi vận hành

- Mọi secret chỉ nằm ở `Key` + các `.env` (không commit). Trình duyệt **không bao giờ** thấy API key (Node giữ).
- Khi sửa `API_KEY`: cập nhật đồng thời `/opt/proxmox-vps-api/.env` (restart service) và `web/.env` (restart web) và `Key`.
- **Đổi mật khẩu đăng nhập web:** sinh hash scrypt mới rồi cập nhật `PANEL_PASS_HASH` trong `web/.env`, restart web. Sinh hash:
  ```bash
  node -e 'const c=require("crypto");const s=c.randomBytes(16).toString("hex");const h=c.scryptSync(process.argv[1],s,64).toString("hex");console.log(s+":"+h)' "MatKhauMoi"
  ```
- Giữ API ở `127.0.0.1` + SSH tunnel cho tới khi có HTTPS + auth đầy đủ.
