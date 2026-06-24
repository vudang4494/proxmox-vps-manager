# Proxmox VPS API

API tự động hoá việc **tạo và quản lý VPS (KVM)** trên Proxmox VE, bằng cách
**clone một template** có sẵn rồi cấu hình CPU/RAM/disk/IP qua **cloud-init**.

Stack: **FastAPI** + **proxmoxer**, xác thực Proxmox bằng **API Token**.

> 🧩 **Đây là source mẫu (template trắng).** Mọi thông tin gắn với môi trường cụ thể —
> IP/host Proxmox, API token, API key, mật khẩu đăng nhập web, node, storage, domain… —
> đều đã được thay bằng **placeholder** (vd `YOUR_PROXMOX_HOST`, `pve`, `change-me`).
> Người clone về **tự điền giá trị của mình** vào `.env` và `web/.env`
> (copy từ `.env.example` / `web/.env.example`). Repo **không kèm bất kỳ secret nào** —
> file `Key` và mọi `.env` đều bị `.gitignore`.

---

## 1. Chuẩn bị trên Proxmox

### a. Tạo template để clone
VPS được tạo bằng cách clone một template. Bạn cần một VM template đã cài sẵn
**cloud-init**. Cách nhanh nhất là dùng cloud image (vd Ubuntu/Debian cloud img):

```bash
# Ví dụ trên node Proxmox (chạy 1 lần để tạo template VMID 9000) — Ubuntu 24.04, cú pháp PVE 8.2+
cd /root
wget -O noble.img https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
qm create 9000 --name ubuntu-2404-tpl --memory 2048 --cores 2 --cpu host \
  --net0 virtio,bridge=vmbr0 --scsihw virtio-scsi-pci --ostype l26
qm set 9000 --scsi0 local-lvm:0,import-from=/root/noble.img
qm set 9000 --ide2 local-lvm:cloudinit
qm set 9000 --boot order=scsi0 --serial0 socket --vga serial0 --agent enabled=1
qm template 9000
```

> Lưu ý disk dùng `scsi0` (mặc định resize trong code này là `scsi0`).

### b. Tạo API Token
`Datacenter → Permissions → API Tokens → Add`:
- User: `root@pam` (hoặc tạo user riêng `apiuser@pve`)
- Token ID: `automation`
- **Bỏ tick** "Privilege Separation" để token kế thừa quyền của user (hoặc cấp
  quyền `VM.Allocate`, `VM.Clone`, `VM.Config.*`, `VM.PowerMgmt`, `Datastore.AllocateSpace`).

Copy lại **Secret** (chỉ hiện 1 lần) để điền vào `.env`.

---

## 2. Cài đặt & chạy

```bash
cd ~/proxmox-vps-manager

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Sửa .env với thông tin Proxmox thật của bạn

# (Khuyến nghị) Kiểm tra kết nối & cấu hình TRƯỚC khi tạo VPS:
python check_connection.py

# --host 0.0.0.0 chỉ dùng cho dev local; production nên 127.0.0.1 + systemd (xem docs/02-trien-khai.md)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Mở tài liệu API tương tác (Swagger UI): http://localhost:8000/docs

### Kiểm tra kết nối (`check_connection.py`)

Khi đã dựng xong Proxmox và điền `.env`, chạy script này để xác nhận token, node,
template, storage và bridge đều đúng. Script **chỉ đọc**, không tạo/sửa/xoá gì:

```bash
python check_connection.py
```

Ví dụ kết quả mong đợi:
```
✅ Xác thực token OK. Proxmox VE version: 9.x.x
✅ Node 'pve' tồn tại.
✅ Template VMID 9000 tồn tại và là template (name='ubuntu-2404-tpl').
✅ Storage 'local-lvm' khả dụng trên node 'pve'.
✅ Bridge 'vmbr0' tồn tại trên node 'pve'.
✅ Tất cả kiểm tra đạt. Sẵn sàng tạo VPS qua API.
```

> **Mô hình triển khai khuyến nghị:** service chạy **ngay trên host Proxmox**
> (`/opt/proxmox-vps-api`, systemd `proxmox-vps-api`, bind `127.0.0.1:8000`) nên
> `PROXMOX_HOST=127.0.0.1` — gọi Proxmox API cục bộ qua cổng 8006. Web panel ở Mac
> (port 9999) tới được FastAPI (cổng `8000`) **và Shell Console** (cổng `8006`) nhờ **SSH tunnel
> forward cả hai cổng**: `ssh -p 22 -N -L 8000:127.0.0.1:8000 -L 8006:127.0.0.1:8006 root@<host>`.
> Chi tiết: `docs/01-kien-truc.md`, `docs/02-trien-khai.md`. *(Service cũng có thể chạy ở máy khác
> rồi trỏ `PROXMOX_HOST` tới IP Proxmox.)*

> **Web panel (`web/`, port 9999):** có **đăng nhập** (session), tạo VPS kèm **User/Pass riêng cho
> mỗi VPS** (quyền sudo, độc lập user Proxmox), **Shell Console** (xterm.js) và xem **chi tiết** từng VM.
> Xem `docs/`.

---

## 3. Các endpoint

Mọi request (trừ `/health`) cần header `X-API-Key: <API_KEY trong .env>`.

| Method | Path                       | Mô tả                                   |
|--------|----------------------------|-----------------------------------------|
| GET    | `/health`                  | Health check                            |
| POST   | `/api/v1/vps`              | Tạo VPS mới (clone template)            |
| GET    | `/api/v1/vps`              | Liệt kê VPS trên node                   |
| GET    | `/api/v1/vps/{vmid}`       | Trạng thái 1 VPS                        |
| GET    | `/api/v1/vps/{vmid}/detail`| Chi tiết cấu hình + trạng thái VPS      |
| POST   | `/api/v1/vps/{vmid}/console`| Mở Shell Console (trả ticket WebSocket) |
| POST   | `/api/v1/vps/{vmid}/start` | Bật VPS                                 |
| POST   | `/api/v1/vps/{vmid}/stop`  | Tắt VPS                                 |
| DELETE | `/api/v1/vps/{vmid}`       | Xoá VPS                                 |

### Ví dụ tạo VPS

```bash
curl -X POST http://localhost:8000/api/v1/vps \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me-please" \
  -d '{
    "name": "web-01",
    "cores": 2,
    "memory_mb": 2048,
    "disk_gb": 20,
    "ci_user": "admin",
    "ci_password": "StrongPass123",
    "ssh_public_key": "ssh-ed25519 AAAA... user@host",
    "ip_address": "192.168.1.50/24",
    "gateway": "192.168.1.1",
    "nameserver": "1.1.1.1",
    "start": true
  }'
```

Response:
```json
{
  "vmid": 101,
  "name": "web-01",
  "node": "pve",
  "status": "running",
  "message": "VPS 'web-01' đã được tạo thành công với VMID 101."
}
```

Bỏ `ip_address` để dùng **DHCP**. Bỏ `disk_gb` để giữ nguyên disk của template.

---

## 4. Luồng xử lý khi tạo VPS

1. `cluster/nextid` → lấy VMID trống.
2. `clone` template → VM mới (chờ task hoàn tất).
3. `config` → set cores, memory, net0, cloud-init (user/pass/sshkeys/ipconfig0).
4. `resize` disk (nếu `disk_gb` được cung cấp).
5. `status/start` → bật VM (nếu `start=true`).

Nếu bước 3–5 lỗi, VM vừa clone sẽ được **tự động xoá (rollback)** để không để rác.

---

## 5. Lưu ý sản xuất (production)

- **Tác vụ dài**: clone full + start có thể mất nhiều giây tới phút. Code hiện chạy
  đồng bộ trong threadpool. Với tải cao nên chuyển sang hàng đợi (Celery/RQ/ARQ) và
  trả về job-id để client poll.
- **Bảo mật**: đặt `PROXMOX_VERIFY_SSL=true` với cert hợp lệ; đổi `API_KEY` mạnh;
  chạy sau reverse proxy có HTTPS.
- **Quyền token**: nên dùng user riêng với quyền tối thiểu thay vì `root@pam`.
- **Multi-node**: truyền `node` trong request, hoặc bổ sung logic chọn node theo tải.

---

## 6. License

Phát hành theo giấy phép **MIT** — xem [LICENSE](LICENSE). Tự do dùng/sửa/phân phối;
chỉ cần điền thông tin cấu hình (Proxmox host, token, mật khẩu…) của riêng bạn.
