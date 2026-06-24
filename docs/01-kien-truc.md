# 01 — Kiến trúc tổng quan

## Mục tiêu hệ thống

Tự động hoá việc **tạo và quản lý VPS (máy ảo KVM)** trên Proxmox: người dùng chọn cấu hình
(CPU/RAM/SSD) trên giao diện web → hệ thống **clone một template** có sẵn → cấu hình lại
tài nguyên + cloud-init → bật máy. Kết quả là một VPS chạy thật.

## Sơ đồ 3 tầng

```
┌──────────────┐   HTTP :9999   ┌─────────────────────┐   HTTP :8000    ┌──────────────────────────┐
│  Trình duyệt  │ ─────────────▶ │  Web panel (Node.js) │ ──────────────▶ │  API service (FastAPI)    │
│   (trên Mac)  │                │  Express · port 9999 │  (qua SSH tunnel)│  /opt/proxmox-vps-api     │
└──────────────┘                │  giữ API key (.env)  │                 │  uvicorn 127.0.0.1:8000    │
                                └─────────────────────┘                 └────────────┬─────────────┘
                                                                                     │ proxmoxer (API token)
                                                                                     ▼ HTTPS :8006
                                                                        ┌──────────────────────────┐
                                                                        │  Proxmox VE — node pve│
                                                                        │  clone template 9000 → VM mới │
                                                                        └──────────────────────────┘
```

## Các thành phần

| Tầng | Thành phần | Chạy ở đâu | Vai trò |
|---|---|---|---|
| 1 | **Web panel** (Node.js/Express) | Máy Mac, port `9999` | **Đăng nhập** (session), chọn preset CPU/RAM/SSD + **User/Pass riêng mỗi VPS**, **Shell Console** (xterm.js) & chi tiết VM, validate, gọi xuống FastAPI. **Giữ API key**. |
| 2 | **API service** (FastAPI + proxmoxer) | Host Proxmox, `127.0.0.1:8000` | REST API tạo/quản lý VPS; nói chuyện với Proxmox qua API token. |
| 3 | **Proxmox VE** | Server `pve` | Hypervisor; thực thi clone/cấu hình/bật VM. |
| — | **Template VMID 9000** | Trên Proxmox | "Khuôn" Ubuntu 24.04 + cloud-init để clone ra mọi VPS. |

> **Lưu ý vị trí:** FastAPI chạy **trên chính host Proxmox** nên `127.0.0.1:8000` là localhost
> *của server*, không phải của Mac. Web panel ở Mac tới được FastAPI nhờ **SSH tunnel**
> chuyển cổng 8000 của Mac sang 8000 của Proxmox.

## Luồng tạo một VPS (end-to-end)

1. Người dùng chọn CPU/RAM/SSD + tên trên web `:9999`, bấm **Tạo**.
2. **Web panel** validate preset (chỉ nhận giá trị cho phép), đổi RAM GB→MB, rồi `POST /api/v1/vps`
   xuống FastAPI kèm header `X-API-Key`.
3. **FastAPI** xác thực key, lấy VMID trống (`cluster/nextid`), rồi qua proxmoxer:
   - `clone` template 9000 → VM mới (chờ task xong).
   - `config` set cores/memory/net0/cloud-init.
   - `resize` disk `scsi0` theo SSD chọn.
   - `start` bật VM.
4. **Proxmox** thực thi: mở rộng disk logic ở bước `resize` (**trước** khi bật máy), rồi `start`.
   Khi VM **boot**, cloud-init mới chạy → nới rộng filesystem lấp đầy disk + áp user/mạng.
5. Kết quả (VMID, status) trả ngược về web hiển thị.

## Công nghệ

| Tầng | Stack |
|---|---|
| Web panel | Node.js (ESM) · Express 4 · HTML/CSS/JS thuần (không framework) |
| API service | Python 3.13 · FastAPI · proxmoxer · uvicorn · Pydantic |
| Hạ tầng | Proxmox VE 8.x/9.x (Debian 12/13) · KVM/QEMU · cloud-init · lvmthin (`local-lvm`) |

> `local-lvm` là storage **LVM thin-provisioned** do Proxmox quản lý: khai báo disk lớn (vd 100GB)
> nhưng chỉ tốn dung lượng thực dùng. Code không có logic thin/full riêng — chỉ truyền `storage` + `disk_gb`.

## Mô hình mạng & cổng

| Cổng | Dịch vụ | Phạm vi |
|---|---|---|
| `9999` | Web panel (Node) | localhost trên Mac |
| `8000` | FastAPI | `127.0.0.1` trên Proxmox (qua SSH tunnel từ Mac) |
| `8006` | Proxmox web/API + **WebSocket console** | mở ra internet (firewall); web panel cũng mở WS console tới cổng này |
| `22` | SSH | chỉ cho IP máy Mac (firewall) |

> **Shell Console (WebSocket):** ngoài luồng REST `:8000`, web panel còn mở một WebSocket tới Proxmox
> `:8006` phục vụ Shell Console (xterm.js). Node BFF chèn header `Authorization: PVEAPIToken=...` ở
> handshake (token giữ phía server, **trình duyệt không bao giờ thấy**). Vì mặc định
> `PROXMOX_WS_URL=https://127.0.0.1:8006`, khi chạy panel **trên Mac** cần SSH tunnel forward **thêm
> cổng 8006** (ngoài 8000) thì console mới hoạt động.

Chi tiết firewall & bảo mật: [04 — Bảo mật](04-bao-mat.md).
