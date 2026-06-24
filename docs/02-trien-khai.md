# 02 — Cài đặt & triển khai

Tài liệu này mô tả cách dựng lại toàn bộ hệ thống từ đầu. Hệ thống hiện tại **đã được
triển khai sẵn** theo các bước này trên server `pve`.

---

## A. Chuẩn bị trên Proxmox

### A.1. Tạo API Token

```bash
# Trên Proxmox (SSH vào). Token toàn quyền — để test; sau nên phân quyền (xem Bảo mật).
pveum user token add root@pam automation --privsep 0 --output-format json
```

Kết quả trả về `value` (secret) — **chỉ hiện 1 lần**, lưu lại để điền vào `.env` của FastAPI.

### A.2. Tạo template cloud-init (VMID 9000)

Đây là "khuôn" để clone ra mọi VPS. Dùng cloud image Ubuntu 24.04:

```bash
# Tải cloud image
cd /root
wget -O noble.img https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img

# Tạo VM 9000 và import disk (cú pháp PVE 8.2+: import-from)
qm create 9000 --name ubuntu-2404-tpl --memory 2048 --cores 2 --cpu host \
  --net0 virtio,bridge=vmbr0 --scsihw virtio-scsi-pci --ostype l26
qm set 9000 --scsi0 local-lvm:0,import-from=/root/noble.img
qm set 9000 --ide2 local-lvm:cloudinit
qm set 9000 --boot order=scsi0 --serial0 socket --vga serial0 --agent enabled=1

# Chuyển thành template
qm template 9000
```

> Disk dùng `scsi0` — **quan trọng**: code resize đĩa mặc định nhắm vào `scsi0`.
> Ổ `ide2` là cloud-init drive (bắt buộc để áp user/mạng).

### A.3. Bật `snippets` cho storage (cần cho User/Pass riêng mỗi VPS)

Khi tạo VPS có **user/mật khẩu riêng**, service ghi một file cloud-init user-data vào
`/var/lib/vz/snippets/` rồi gắn qua `cicustom`. Storage phải bật loại nội dung **`snippets`**
(chạy **1 lần**):

```bash
pvesm set local --content iso,vztmpl,backup,import,snippets
```

> Nếu chưa bật, request tạo VPS có `ci_user` sẽ lỗi `500` kèm hướng dẫn chạy đúng lệnh trên.
> Bỏ trống user/pass thì không cần bước này.

---

## B. Triển khai FastAPI service

Service chạy **ngay trên host Proxmox** (Debian 13).

### B.1. Copy code & cài môi trường

```bash
# Từ máy dev, đẩy code lên server (loại trừ secret & venv)
rsync -az -e "ssh -p 22" \
  --exclude='.venv' --exclude='__pycache__' --exclude='.env' --exclude='Key' \
  --exclude='node_modules' --exclude='*.log' --exclude='.DS_Store' \
  ~/proxmox-vps-manager/ root@YOUR_PROXMOX_HOST:/opt/proxmox-vps-api/

# Trên server: cài venv + deps
apt-get install -y python3-venv
cd /opt/proxmox-vps-api
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### B.2. File cấu hình `/opt/proxmox-vps-api/.env`

```ini
PROXMOX_HOST=127.0.0.1
PROXMOX_PORT=8006
PROXMOX_USER=root@pam
PROXMOX_TOKEN_NAME=automation
PROXMOX_TOKEN_VALUE=<secret token ở bước A.1>
PROXMOX_VERIFY_SSL=false
DEFAULT_NODE=pve
DEFAULT_TEMPLATE_ID=9000
DEFAULT_STORAGE=local-lvm
DEFAULT_BRIDGE=vmbr0
API_KEY=<chuỗi ngẫu nhiên mạnh>          # vd: openssl rand -hex 32
```

> Đặt quyền `chmod 600 .env`. Sinh API key mạnh: `openssl rand -hex 32`.

### B.3. Kiểm tra kết nối (chỉ đọc, không tạo VM)

```bash
.venv/bin/python check_connection.py
```

Script kiểm tra 5 thứ: (1) token Proxmox hợp lệ, (2) node `pve` tồn tại, (3) template VMID 9000
là template hợp lệ (báo ⚠️ nếu thiếu cloud-init drive — **không** chặn tạo VM), (4) storage `local-lvm`,
(5) bridge `vmbr0`. Mong đợi: token/node/storage/bridge đều ✅.

### B.4. systemd service `/etc/systemd/system/proxmox-vps-api.service`

```ini
[Unit]
Description=Proxmox VPS API (FastAPI)
After=network-online.target pveproxy.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/proxmox-vps-api
ExecStart=/opt/proxmox-vps-api/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now proxmox-vps-api.service
systemctl status proxmox-vps-api.service     # mong đợi: active (running)
```

---

## C. Triển khai Web panel (Node.js)

Web panel chạy trên **máy dev (Mac)**, port `9999`.

```bash
cd ~/proxmox-vps-manager/web
npm install
```

### File cấu hình `web/.env`

```ini
PORT=9999
PROXMOX_API_URL=http://127.0.0.1:8000     # qua SSH tunnel (xem dưới)
API_KEY=<đúng API_KEY trong .env của FastAPI>

# Đăng nhập web panel (BẮT BUỘC — thiếu PANEL_PASS_HASH thì không đăng nhập được)
PANEL_USER=<tên đăng nhập web>
PANEL_PASS_HASH=<salt:scryptHex>          # mật khẩu lưu hash scrypt, không plaintext (lệnh sinh ở dưới)
SESSION_SECRET=<chuỗi ngẫu nhiên>          # nên đặt để phiên sống qua restart: openssl rand -hex 32

# Shell Console (xterm.js) — cần cổng 8006 (xem tunnel ở dưới)
PROXMOX_WS_URL=https://127.0.0.1:8006
```

Sinh `PANEL_PASS_HASH` (dạng `salt:scryptHex`):

```bash
node -e 'const c=require("crypto");const s=c.randomBytes(16).toString("hex");const h=c.scryptSync(process.argv[1],s,64).toString("hex");console.log(s+":"+h)' '<mật-khẩu-của-bạn>'
```

### Chạy

```bash
# 1) Mở SSH tunnel để Node tới được FastAPI (8000) và Shell Console Proxmox (8006)
ssh -p 22 -N -L 8000:127.0.0.1:8000 -L 8006:127.0.0.1:8006 root@YOUR_PROXMOX_HOST &

# 2) Chạy web
npm start            # http://localhost:9999
```

---

## Tóm tắt vị trí file

| Thành phần | Đường dẫn |
|---|---|
| Code FastAPI (dev) | `~/proxmox-vps-manager/app/` |
| FastAPI (server) | `/opt/proxmox-vps-api/` |
| Cấu hình FastAPI | `/opt/proxmox-vps-api/.env` |
| systemd unit | `/etc/systemd/system/proxmox-vps-api.service` |
| Template image | `/root/noble.img` (trên server) |
| Web panel | `~/proxmox-vps-manager/web/` |
| Cấu hình web | `web/.env` |
| Credentials tổng hợp | `Key` — file cục bộ (dev) gom mọi bí mật (API_KEY, Proxmox token, SSH pass) để tra cứu; **gitignored, không commit** |
