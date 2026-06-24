# Hướng dẫn sử dụng Proxmox VPS API

Tài liệu chi tiết cách **gọi API** để tự động tạo / quản lý VPS (KVM) trên Proxmox.

> **Tóm tắt 30 giây**
> 1. Mở SSH tunnel: `ssh -p 22 -L 8000:127.0.0.1:8000 root@YOUR_PROXMOX_HOST`
> 2. Lấy API key trong file `Key` (mục `API_KEY=...`).
> 3. Gọi: `curl http://localhost:8000/api/v1/vps -H "X-API-Key: <API_KEY>"`
> 4. Hoặc mở trình duyệt: `http://localhost:8000/docs` (Swagger UI).
> 5. Hoặc dùng **Web Panel** (giao diện): `http://localhost:9999` — có đăng nhập, form tạo VPS và **Shell Console**. Chạy bằng Node/Express (`web/`), giữ API key ở server-side. Chi tiết: `docs/01-kien-truc.md`, `docs/03-van-hanh.md`.

---

## 1. Tổng quan

- **API làm gì:** nhận request HTTP → ra lệnh cho Proxmox **clone một template** (VMID `9000`, Ubuntu 24.04 có cloud-init) → cấu hình CPU/RAM/disk/mạng qua cloud-init → bật máy. Kết quả là một VPS mới chạy thật.
- **Chạy ở đâu:** service `proxmox-vps-api` (systemd) chạy **ngay trên host Proxmox** `pve`, lắng nghe `127.0.0.1:8000`.
- **Vì sao chỉ nghe 127.0.0.1:** để không phơi API (tạo/xoá được VM) ra Internet. Bạn truy cập qua **SSH tunnel** từ máy mình.
- **Định dạng:** request/response đều là **JSON**. Header `Content-Type: application/json` cho các request có body.

---

## 2. Kết nối & truy cập

API chỉ nghe trên `127.0.0.1` của server, nên từ máy bạn cần **SSH tunnel** chuyển cổng `8000` về máy local.

```bash
# Mở 1 terminal và GIỮ MỞ trong lúc làm việc:
ssh -p 22 -L 8000:127.0.0.1:8000 root@YOUR_PROXMOX_HOST
```

Sau khi tunnel mở, mọi request tới `http://localhost:8000` trên máy bạn sẽ được chuyển tới API trên server.

| Cách dùng | URL |
|---|---|
| Swagger UI (thử API bằng trình duyệt) | http://localhost:8000/docs |
| ReDoc (đọc tài liệu) | http://localhost:8000/redoc |
| OpenAPI spec (JSON) | http://localhost:8000/openapi.json |
| Base URL khi gọi bằng curl/code | `http://localhost:8000` |

> Nếu đang SSH thẳng trên server thì dùng `http://127.0.0.1:8000` (không cần tunnel).

---

## 3. Xác thực (Authentication)

Mọi endpoint dưới `/api/v1/vps` **bắt buộc** gửi header:

```
X-API-Key: <API_KEY>
```

`<API_KEY>` nằm trong file [`Key`](Key) (dòng `API_KEY=...`). Endpoint `/health` **không** cần key.

Cho tiện, đặt key vào biến môi trường rồi tái dùng:

```bash
export APIKEY="<dán API_KEY từ file Key>"   # lấy từ file Key (dòng API_KEY=...)
curl http://localhost:8000/api/v1/vps -H "X-API-Key: $APIKEY"
```

**Kết quả xác thực:**

| Tình huống | HTTP | Body |
|---|---|---|
| Đúng key | tiếp tục xử lý | tuỳ endpoint |
| Sai key | `401` | `{"detail":"X-API-Key không hợp lệ hoặc thiếu."}` |
| Thiếu header key | `401` | `{"detail":"X-API-Key không hợp lệ hoặc thiếu."}` |

**Quy tắc xác thực (quan trọng):**
- `/health` là endpoint **duy nhất** không cần key.
- **Toàn bộ** endpoint dưới `/api/v1/*` **bắt buộc** header `X-API-Key`; thiếu/sai → `401`.
- ⚠️ **Bảo mật:** nếu `API_KEY` trong `.env` để **rỗng**, service sẽ **bỏ qua xác thực** — mọi endpoint mở tự do. Chỉ dùng khi test cục bộ; production phải đặt `API_KEY` mạnh.

---

## 4. Danh sách endpoint

| Method | Path | Auth | Mô tả |
|---|---|:---:|---|
| `GET` | `/health` | ❌ | Kiểm tra service sống |
| `POST` | `/api/v1/vps` | ✅ | **Tạo VPS mới** (clone template) |
| `GET` | `/api/v1/vps` | ✅ | Liệt kê VPS trên node |
| `GET` | `/api/v1/vps/{vmid}` | ✅ | Xem trạng thái 1 VPS |
| `GET` | `/api/v1/vps/{vmid}/detail` | ✅ | Chi tiết cấu hình + trạng thái (disk/IP/bridge/ostype/uptime) |
| `POST` | `/api/v1/vps/{vmid}/console` | ✅ | Mở Shell Console — trả ticket cho WebSocket |
| `POST` | `/api/v1/vps/{vmid}/start` | ✅ | Bật VPS |
| `POST` | `/api/v1/vps/{vmid}/stop` | ✅ | Tắt VPS |
| `DELETE` | `/api/v1/vps/{vmid}` | ✅ | Xoá VPS |

---

## 5. Chi tiết từng endpoint

### 5.1. `GET /health` — Health check

Không cần API key. Dùng để kiểm tra service có sống không.

```bash
curl http://localhost:8000/health
```
```json
{"status":"ok","version":"0.1.0"}
```

---

### 5.2. `POST /api/v1/vps` — Tạo VPS mới

Endpoint chính. Clone template → cấu hình → (tuỳ chọn) bật máy. Trả về `201 Created`.

**Tham số trong body (JSON):**

| Trường | Kiểu | Bắt buộc | Mặc định | Ràng buộc / Ghi chú |
|---|---|:---:|---|---|
| `name` | string | ✅ | — | Hostname VM. Chỉ gồm chữ, số, dấu `-`. |
| `cores` | int | ❌ | `2` | 1 ≤ cores ≤ 128 (số vCPU). |
| `memory_mb` | int | ❌ | `2048` | ≥ 128 (RAM theo MB). |
| `disk_gb` | int | ❌ | `null` | ≥ 1. **Phải ≥ disk template** (template hiện ~3.5GB). Bỏ trống = giữ nguyên disk template. |
| `ci_user` | string | ❌ | `null` | User cloud-init tạo trong VM. |
| `ci_password` | string | ❌ | `null` | Mật khẩu cho `ci_user`. |
| `ssh_public_key` | string | ❌ | `null` | Nội dung SSH public key, nạp vào `authorized_keys`. |
| `ip_address` | string | ❌ | `null` | IP tĩnh dạng CIDR, vd `192.168.1.50/24`. **Bỏ trống = DHCP.** |
| `gateway` | string | ❌ | `null` | Default gateway (đi kèm `ip_address`). |
| `nameserver` | string | ❌ | `null` | DNS server, vd `1.1.1.1`. |
| `node` | string | ❌ | `pve` *(.env)* | Node Proxmox để tạo VM. Bỏ trống = `DEFAULT_NODE` trong `.env`. |
| `template_id` | int | ❌ | `9000` *(.env)* | VMID template để clone. Bỏ trống = `DEFAULT_TEMPLATE_ID`. |
| `storage` | string | ❌ | `local-lvm` *(.env)* | Storage chứa disk VM. Bỏ trống = `DEFAULT_STORAGE`. |
| `bridge` | string | ❌ | `vmbr0` *(.env)* | Network bridge gắn card mạng. Bỏ trống = `DEFAULT_BRIDGE`. |
| `full_clone` | bool | ❌ | `true` | `true` = full clone (độc lập); `false` = linked clone. Xem ghi chú bên dưới. |
| `start` | bool | ❌ | `true` | Bật VM ngay sau khi tạo. |

**Ghi chú thêm về một số trường:**
- **`node` / `template_id` / `storage` / `bridge`**: ở tầng schema (Pydantic) mặc định là `null`; nếu **bỏ trống** trong body, service tự điền từ file `.env` server (`/opt/proxmox-vps-api/.env`). Cột "Mặc định" ở trên là giá trị `.env` mặc định (`pve` / `9000` / `local-lvm` / `vmbr0`). Gửi giá trị trong body để **override** từng request.
- **`full_clone`**: `true` (mặc định) copy toàn bộ disk → VM **độc lập** với template (xoá template vẫn chạy), nhưng tạo lâu & tốn dung lượng hơn. `false` (linked clone) dùng snapshot template → tạo **nhanh & tiết kiệm**, nhưng **không được xoá template** (xoá sẽ hỏng VM con).
- **`ci_password` / `ssh_public_key`**: chỉ có tác dụng khi đặt `ci_user`. Nên ưu tiên `ssh_public_key` thay vì mật khẩu cho an toàn. Mật khẩu nên thoả yêu cầu cloud-init (đủ dài, có chữ/số/ký tự đặc biệt).
- **`disk_gb`**: resize được thực hiện trên disk **`scsi0`** (template `9000` dùng `scsi0`). Nếu template của bạn dùng tên disk khác (`virtio0`, `sata0`...), bước resize sẽ báo lỗi `400`. Chỉ **tăng** được, không giảm.
- **`ip_address` / `gateway`**: `gateway` **chỉ có tác dụng khi có** `ip_address` (IP tĩnh). Nếu dùng DHCP (bỏ trống `ip_address`) thì `gateway` bị **bỏ qua**.
- **`nameserver`**: set DNS trong VM qua cloud-init, hoạt động **độc lập**, không phụ thuộc trường khác.

**Ví dụ tối giản** (chỉ cần `name`, còn lại dùng mặc định, mạng DHCP):

```bash
curl -X POST http://localhost:8000/api/v1/vps \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $APIKEY" \
  -d '{"name":"web-01"}'
```

**Ví dụ đầy đủ** (đặt CPU/RAM/disk, user + SSH key, IP tĩnh):

```bash
curl -X POST http://localhost:8000/api/v1/vps \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $APIKEY" \
  -d '{
    "name": "web-01",
    "cores": 2,
    "memory_mb": 2048,
    "disk_gb": 20,
    "ci_user": "admin",
    "ci_password": "StrongPass123!",
    "ssh_public_key": "ssh-ed25519 AAAA... user@host",
    "ip_address": "192.168.1.50/24",
    "gateway": "192.168.1.1",
    "nameserver": "1.1.1.1",
    "start": true
  }'
```

**Ví dụ override mặc định** (chỉ định node/template/storage/bridge khác `.env` — thay bằng giá trị thật trên hệ thống của bạn):

```bash
curl -X POST http://localhost:8000/api/v1/vps \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $APIKEY" \
  -d '{
    "name": "db-01",
    "cores": 4,
    "memory_mb": 8192,
    "node": "pve",
    "template_id": 9000,
    "storage": "local-lvm",
    "bridge": "vmbr0",
    "full_clone": false
  }'
```

**Response `201`** (kiểu `CreateVPSResponse`):

```json
{
  "vmid": 100,
  "name": "web-01",
  "node": "pve",
  "status": "running",
  "message": "VPS 'web-01' đã được tạo thành công với VMID 100."
}
```

- `vmid` do Proxmox cấp tự động (lấy từ `cluster/nextid`).
- `status` = `running` nếu `start=true`, ngược lại `stopped`.
- **Rollback:** nếu một bước **sau khi clone thành công** bị lỗi (cấu hình / resize / start), VM vừa clone sẽ được **tự động xoá** để không để rác. Nếu **bước clone** lỗi thì VM chưa được tạo (không cần rollback). Trường hợp hiếm: nếu việc xoá rollback cũng thất bại, VM lỗi sẽ **còn lại** trên Proxmox và cần dọn thủ công (xem §10).
- Tạo VPS là thao tác **đồng bộ**: API **chờ task clone và start** hoàn tất (timeout mỗi task 300s) rồi mới trả response. Các bước cấu hình CPU/RAM/mạng và resize disk là lệnh tức thời (không phải task chờ). Một request tạo có thể mất vài giây đến vài chục giây.

> **Lưu ý mạng trên server này:** bridge `vmbr0` là mạng **public**. Nếu nhà cung cấp không cấp IP qua DHCP, VPS tạo bằng DHCP sẽ không có IP — khi đó truyền `ip_address` + `gateway` tĩnh phù hợp.

---

### 5.3. `GET /api/v1/vps` — Liệt kê VPS

Liệt kê toàn bộ VM (kể cả template) trên node. Trả về mảng `VPSInfo`.

**Query param (tuỳ chọn):** `node` — node Proxmox (bỏ trống = `pve`).

```bash
curl http://localhost:8000/api/v1/vps -H "X-API-Key: $APIKEY"
# Chỉ định node khác:
curl "http://localhost:8000/api/v1/vps?node=pve" -H "X-API-Key: $APIKEY"
```
```json
[
  {"vmid":9000,"name":"ubuntu-2404-tpl","node":"pve","status":"stopped","cores":2,"memory_mb":2048,"uptime":0},
  {"vmid":100,"name":"web-01","node":"pve","status":"running","cores":2,"memory_mb":2048,"uptime":37}
]
```

---

### 5.4. `GET /api/v1/vps/{vmid}` — Xem 1 VPS

Trả về `VPSInfo` của VM có `vmid`.

**Query param (tuỳ chọn):** `node`.

```bash
curl http://localhost:8000/api/v1/vps/100 -H "X-API-Key: $APIKEY"
```
```json
{"vmid":100,"name":"web-01","node":"pve","status":"running","cores":2,"memory_mb":2048,"uptime":37}
```

VM không tồn tại → `404`.

---

### 5.5. `GET /api/v1/vps/{vmid}/detail` — Chi tiết cấu hình + trạng thái

Gộp `config` + `status` của VM (dùng cho trang chi tiết trên web). Trả về `VPSDetail`.

**Query param (tuỳ chọn):** `node`.

```bash
curl http://localhost:8000/api/v1/vps/100/detail -H "X-API-Key: $APIKEY"
```
```json
{
  "vmid": 100, "name": "web-01", "node": "pve", "status": "running",
  "cores": 4, "memory_mb": 4096, "disk_gb": 100,
  "ip_config": "ip=dhcp", "bridge": "vmbr0", "ostype": "l26", "uptime": 1234
}
```

---

### 5.6. `POST /api/v1/vps/{vmid}/console` — Mở Shell Console

Tạo phiên **serial terminal** qua Proxmox `termproxy` (xác thực bằng **API token**) và trả về ticket để
mở **WebSocket** tới Proxmox. Trả về `ConsoleTicket`.

```bash
curl -X POST http://localhost:8000/api/v1/vps/100/console -H "X-API-Key: $APIKEY"
```
```json
{
  "node": "pve", "vmid": 100, "port": 5900,
  "ticket": "PVEVNC:....", "user": "root@pam!automation",
  "auth_header": "PVEAPIToken=root@pam!automation=...."
}
```

> Endpoint này chỉ **cấp ticket**. Việc nối WebSocket tới `wss://<host>:8006/.../vncwebsocket` do web
> panel (Node) thực hiện — Node chèn header `Authorization: <auth_header>` ở bước upgrade, browser không
> bao giờ thấy token. Muốn dùng console qua tunnel cần **forward thêm cổng 8006** (xem §2). Giao thức
> xterm.js: `user:ticket\n` → `1:cols:rows:` (resize) → `0:len:data` (input) → `2` (keepalive).

---

### 5.7. `POST /api/v1/vps/{vmid}/start` — Bật VPS

Bật VM rồi trả về `VPSInfo` mới nhất.

```bash
curl -X POST http://localhost:8000/api/v1/vps/100/start -H "X-API-Key: $APIKEY"
```
```json
{"vmid":100,"name":"web-01","node":"pve","status":"running","cores":2,"memory_mb":2048,"uptime":2}
```

---

### 5.8. `POST /api/v1/vps/{vmid}/stop` — Tắt VPS

Tắt VM (hard stop) rồi trả về `VPSInfo`.

```bash
curl -X POST http://localhost:8000/api/v1/vps/100/stop -H "X-API-Key: $APIKEY"
```
```json
{"vmid":100,"name":"web-01","node":"pve","status":"stopped","cores":2,"memory_mb":2048,"uptime":0}
```

> **Start/stop là đồng bộ:** API chờ task hoàn tất trên Proxmox (timeout 300s) rồi mới đọc lại và trả `VPSInfo`. Nếu timeout (`504`) hoặc lỗi (`400`/`502`), trạng thái trả về có thể chưa phản ánh đúng — kiểm tra lại bằng `GET /api/v1/vps/{vmid}`. Lưu ý `stop` là **hard stop** (tắt cứng), không phải shutdown mềm trong OS — ⚠️ có thể **mất/hỏng dữ liệu** nếu trong VM đang có dịch vụ ghi (DB...). Nếu cần an toàn, hãy shutdown mềm từ bên trong VM trước.

---

### 5.9. `DELETE /api/v1/vps/{vmid}` — Xoá VPS

Xoá hẳn VM. Nếu VM đang chạy, API sẽ **tự tắt trước (hard stop, đồng bộ) rồi mới xoá** — cả hai bước đều chờ task Proxmox hoàn tất (timeout mỗi bước 300s). Chỉ trả `204 No Content` (body rỗng) khi **toàn bộ** thành công; nếu bước tắt hoặc xoá lỗi sẽ trả mã lỗi tương ứng (`400`/`502`/`504`).

```bash
curl -X DELETE http://localhost:8000/api/v1/vps/100 \
  -H "X-API-Key: $APIKEY" \
  -w "HTTP %{http_code}\n"
```
```
HTTP 204
```

> ⚠️ Thao tác **không hoàn tác được** — disk của VM bị xoá luôn (`purge`).

---

## 6. Bảng mã lỗi (HTTP status)

| HTTP | Khi nào | Body mẫu |
|---|---|---|
| `200` | GET / start / stop thành công | dữ liệu tương ứng |
| `201` | Tạo VPS thành công | `CreateVPSResponse` |
| `204` | Xoá thành công | (rỗng) |
| `401` | Sai/thiếu `X-API-Key` | `{"detail":"X-API-Key không hợp lệ hoặc thiếu."}` |
| `404` | VMID không tồn tại | `{"detail":"Không lấy được trạng thái VM ..."}` |
| `422` | Body sai schema (vd `name` rỗng, `cores` ngoài 1–128) | `{"detail":[{...}]}` (chi tiết field lỗi) |
| `400` | Proxmox từ chối lệnh (vd template không tồn tại, disk nhỏ hơn template) | `{"detail":"..."}` |
| `502` | Proxmox trả lỗi không xác định | `{"detail":"..."}` |
| `503` | Không kết nối được Proxmox (host/cổng/mạng) | `{"detail":"Không kết nối được tới Proxmox..."}` |
| `504` | Proxmox phản hồi quá thời gian (timeout) | `{"detail":"Proxmox phản hồi quá thời gian (timeout)."}` |

**Các nguyên nhân `400` thường gặp** (luôn đọc `detail` trong body để biết chính xác):
- `template_id` không tồn tại hoặc không clone được.
- `disk_gb` nhỏ hơn dung lượng disk của template (chỉ tăng được, không giảm).
- `storage` / `bridge` không tồn tại trên node.
- Định dạng sai: `ip_address` không đúng CIDR, `ssh_public_key` sai format.
- Bật/tắt/xoá VM ở trạng thái không hợp lệ.

> Phân biệt: `422` là do **request sai schema** (validate ở tầng API, trước khi gọi Proxmox); `400` là **Proxmox từ chối** lệnh đã hợp lệ về schema.

---

## 7. Ví dụ end-to-end (curl)

```bash
# 0) Tunnel (terminal riêng) + đặt key
ssh -p 22 -L 8000:127.0.0.1:8000 root@YOUR_PROXMOX_HOST   # giữ mở
export APIKEY="...lấy từ file Key..."
BASE=http://localhost:8000

# 1) Tạo VPS
curl -X POST $BASE/api/v1/vps -H "Content-Type: application/json" -H "X-API-Key: $APIKEY" \
  -d '{"name":"demo-01","cores":1,"memory_mb":512,"disk_gb":10,"ci_user":"admin","ci_password":"Pass123!"}'

# 2) Xem danh sách / chi tiết (giả sử vmid=100)
curl $BASE/api/v1/vps -H "X-API-Key: $APIKEY"
curl $BASE/api/v1/vps/100 -H "X-API-Key: $APIKEY"
curl $BASE/api/v1/vps/100/detail -H "X-API-Key: $APIKEY"   # cấu hình đầy đủ (disk/IP/bridge)

# 3) Tắt / bật
curl -X POST $BASE/api/v1/vps/100/stop  -H "X-API-Key: $APIKEY"
curl -X POST $BASE/api/v1/vps/100/start -H "X-API-Key: $APIKEY"

# 4) Xoá
curl -X DELETE $BASE/api/v1/vps/100 -H "X-API-Key: $APIKEY" -w "\nHTTP %{http_code}\n"
```

---

## 8. Ví dụ client bằng Python

```python
import requests

BASE = "http://localhost:8000"          # nhớ mở SSH tunnel trước
APIKEY = "...lấy từ file Key..."
HEADERS = {"X-API-Key": APIKEY}

# Tạo VPS
resp = requests.post(
    f"{BASE}/api/v1/vps",
    headers=HEADERS,
    json={
        "name": "demo-01",
        "cores": 1,
        "memory_mb": 512,
        "disk_gb": 10,
        "ci_user": "admin",
        "ci_password": "Pass123!",
        # "ip_address": "192.168.1.50/24", "gateway": "192.168.1.1",  # bỏ = DHCP
    },
    timeout=120,
)
resp.raise_for_status()
vm = resp.json()
print("Đã tạo:", vm)               # {'vmid': 100, 'status': 'running', ...}
vmid = vm["vmid"]

# Xem trạng thái
print(requests.get(f"{BASE}/api/v1/vps/{vmid}", headers=HEADERS).json())

# Xoá
r = requests.delete(f"{BASE}/api/v1/vps/{vmid}", headers=HEADERS, timeout=120)
print("Xoá:", r.status_code)        # 204
```

---

## 9. Quản lý service trên server (systemd)

```bash
ssh -p 22 root@YOUR_PROXMOX_HOST        # vào server

systemctl status  proxmox-vps-api     # trạng thái
systemctl restart proxmox-vps-api     # khởi động lại (vd sau khi sửa .env)
systemctl stop    proxmox-vps-api     # dừng
journalctl -u proxmox-vps-api -f      # xem log realtime
```

- Code đặt tại `/opt/proxmox-vps-api`, cấu hình trong `/opt/proxmox-vps-api/.env`.
- Đổi cấu hình (kể cả `API_KEY`, node/template/storage mặc định) → sửa `.env` rồi `systemctl restart proxmox-vps-api`.
- Kiểm tra nhanh kết nối Proxmox (không tạo VM): `cd /opt/proxmox-vps-api && .venv/bin/python check_connection.py`.

---

## 10. Troubleshooting

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `curl: Connection refused` ở localhost:8000 | Chưa mở SSH tunnel / tunnel rớt | Mở lại tunnel mục 2. |
| Tất cả request `401` | Sai/thiếu `X-API-Key` | Kiểm tra lại key trong file `Key`. |
| `422` khi tạo | Body sai (vd `name` có ký tự lạ, `cores`>128) | Đọc `detail` để biết field lỗi. |
| `400` "Clone template ... thất bại" | `template_id` sai hoặc template không tồn tại | Dùng `template_id=9000`, hoặc kiểm tra `qm list`. |
| `400` resize disk | `disk_gb` nhỏ hơn disk template | Đặt `disk_gb` ≥ kích thước template (~3.5GB trở lên). |
| `503` | Service không nói chuyện được với Proxmox | Kiểm tra `systemctl status pveproxy`, `.env` (`PROXMOX_HOST/PORT/TOKEN`). |
| VPS tạo xong nhưng không có IP | `vmbr0` là mạng public, không có DHCP | Truyền `ip_address` + `gateway` tĩnh. |
| Service không chạy sau reboot | — | Đã `enable`; kiểm tra `systemctl status proxmox-vps-api` và `journalctl`. |

---

## 11. Bảo mật & khuyến nghị

- **Không commit** file `Key` và `.env` (đã thêm vào `.gitignore`).
- API key hiện là chuỗi ngẫu nhiên 64 ký tự hex — đủ mạnh. Đổi khi cần: sửa `API_KEY` trong `.env` rồi restart, cập nhật lại file `Key`.
- Proxmox token hiện là `root@pam!automation` **toàn quyền** (để test). Khi ổn định nên đổi sang token *privilege-separated* + role `PVEVMAdmin` cho an toàn.
- Giữ API ở `127.0.0.1` + SSH tunnel. Nếu sau này cần mở ra ngoài, đặt sau reverse proxy có HTTPS và rate-limit.
