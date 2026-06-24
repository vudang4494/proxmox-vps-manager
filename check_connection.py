"""Kiểm tra kết nối & cấu hình Proxmox trước khi tạo VPS thật.

Chạy:  python check_connection.py
Đọc thông tin từ .env (giống API). Script này CHỈ ĐỌC — không tạo/sửa/xoá gì.

Mục đích: khi bạn vừa dựng xong Proxmox và điền .env, chạy script này để xác nhận
mọi thứ đã đúng (token, node, template, storage, bridge) trước khi gọi API tạo VPS.
"""

import sys

import requests

from app.config import get_settings
from app.proxmox_client import ProxmoxClient

OK = "✅"
FAIL = "❌"
WARN = "⚠️"


def main() -> int:
    # 1) Đọc cấu hình từ .env
    try:
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001 - báo lỗi cấu hình thân thiện
        print(f"{FAIL} Không đọc được cấu hình (.env):\n   {exc}")
        print("   → Copy .env.example thành .env rồi điền thông tin Proxmox thật.")
        return 1

    print(f"→ Đang kết nối https://{settings.proxmox_host}:{settings.proxmox_port} "
          f"(user={settings.proxmox_user}, token={settings.proxmox_token_name}) ...\n")

    failures = 0

    # 2) Xác thực token + lấy version
    try:
        client = ProxmoxClient(settings)
        ver = client.api.version.get()
        print(f"{OK} Xác thực token OK. Proxmox VE version: {ver.get('version', '?')}")
    except requests.exceptions.RequestException as exc:
        print(f"{FAIL} Không kết nối được tới Proxmox (host/cổng/mạng?):\n   {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - thường là token sai → 401
        print(f"{FAIL} Kết nối được nhưng xác thực thất bại (token sai/thiếu quyền?):\n   {exc}")
        return 1

    # 3) Node
    node = settings.default_node
    node_ok = False
    try:
        nodes = [n["node"] for n in client.api.nodes.get()]
        if node in nodes:
            print(f"{OK} Node '{node}' tồn tại.")
            node_ok = True
        else:
            print(f"{FAIL} Node '{node}' KHÔNG tồn tại. Các node hiện có: {nodes}")
            failures += 1
    except Exception as exc:  # noqa: BLE001
        print(f"{FAIL} Không liệt kê được node: {exc}")
        failures += 1

    # Các kiểm tra dưới đây cần node hợp lệ
    if node_ok:
        # 4) Template để clone
        tpl = settings.default_template_id
        try:
            cfg = client.api.nodes(node).qemu(tpl).config.get()
            if cfg.get("template") == 1:
                print(f"{OK} Template VMID {tpl} tồn tại và là template "
                      f"(name='{cfg.get('name', '?')}').")
            else:
                print(f"{WARN} VMID {tpl} tồn tại nhưng KHÔNG phải template "
                      f"(name='{cfg.get('name', '?')}'). Full-clone vẫn được, "
                      f"nhưng linked-clone thì không.")
            if "ide2" not in cfg and "scsi2" not in cfg and not any(
                "cloudinit" in str(v) for v in cfg.values()
            ):
                print(f"{WARN} Không thấy ổ cloud-init trong template {tpl}. "
                      f"Cấu hình IP/user qua cloud-init có thể không tác dụng.")
        except requests.exceptions.RequestException as exc:
            print(f"{FAIL} Lỗi mạng khi đọc template {tpl}: {exc}")
            failures += 1
        except Exception:  # noqa: BLE001 - 404 = không tồn tại
            print(f"{FAIL} Template VMID {tpl} KHÔNG tồn tại trên node '{node}'. "
                  f"→ Tạo template cloud-init trước (xem README).")
            failures += 1

        # 5) Storage
        storage = settings.default_storage
        try:
            storages = [s["storage"] for s in client.api.nodes(node).storage.get()]
            if storage in storages:
                print(f"{OK} Storage '{storage}' khả dụng trên node '{node}'.")
            else:
                print(f"{FAIL} Storage '{storage}' KHÔNG có. Khả dụng: {storages}")
                failures += 1
        except Exception as exc:  # noqa: BLE001
            print(f"{WARN} Không kiểm tra được storage: {exc}")

        # 6) Network bridge
        bridge = settings.default_bridge
        try:
            ifaces = client.api.nodes(node).network.get()
            bridges = [i["iface"] for i in ifaces if i.get("type") == "bridge"]
            if bridge in bridges:
                print(f"{OK} Bridge '{bridge}' tồn tại trên node '{node}'.")
            else:
                print(f"{FAIL} Bridge '{bridge}' KHÔNG có. Các bridge: {bridges}")
                failures += 1
        except Exception as exc:  # noqa: BLE001
            print(f"{WARN} Không kiểm tra được network bridge: {exc}")

    # Kết luận
    print()
    if failures == 0:
        print(f"{OK} Tất cả kiểm tra đạt. Sẵn sàng tạo VPS qua API.")
        return 0
    print(f"{FAIL} Có {failures} mục lỗi. Sửa cấu hình trong .env hoặc trên Proxmox rồi chạy lại.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
