"""Lớp bao bọc proxmoxer: kết nối và các thao tác trên VM (QEMU)."""

import time
import urllib.parse
from typing import Optional

from proxmoxer import ProxmoxAPI
from proxmoxer.core import ResourceException

from .config import Settings


class ProxmoxError(Exception):
    """Lỗi nghiệp vụ phía Proxmox để API trả về HTTP phù hợp."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ProxmoxClient:
    """Bao bọc các thao tác Proxmox cần cho việc cấp VPS.

    proxmoxer dùng `requests` (blocking) nên các method ở đây là đồng bộ;
    FastAPI sẽ chạy chúng trong threadpool khi route khai báo dạng `def`.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._api = ProxmoxAPI(
            host=settings.proxmox_host,
            port=settings.proxmox_port,
            user=settings.proxmox_user,
            token_name=settings.proxmox_token_name,
            token_value=settings.proxmox_token_value,
            verify_ssl=settings.proxmox_verify_ssl,
        )

    # ----- Helpers -----

    @property
    def api(self) -> ProxmoxAPI:
        return self._api

    def next_vmid(self) -> int:
        """Lấy VMID khả dụng tiếp theo từ cluster."""
        return int(self._api.cluster.nextid.get())

    def wait_for_task(self, node: str, upid: str, timeout: int = 300, interval: float = 2.0) -> None:
        """Chờ một task (UPID) của Proxmox hoàn tất.

        Raise ProxmoxError nếu task lỗi hoặc quá thời gian chờ.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self._api.nodes(node).tasks(upid).status.get()
            if status.get("status") == "stopped":
                exit_status = status.get("exitstatus", "")
                if exit_status != "OK":
                    raise ProxmoxError(
                        f"Task Proxmox thất bại (UPID={upid}): {exit_status}", status_code=502
                    )
                return
            time.sleep(interval)
        raise ProxmoxError(f"Task Proxmox quá thời gian chờ ({timeout}s): {upid}", status_code=504)

    def vm_exists(self, node: str, vmid: int) -> bool:
        try:
            self._api.nodes(node).qemu(vmid).status.current.get()
            return True
        except ResourceException:
            return False

    # ----- Thao tác chính -----

    def clone_template(
        self,
        node: str,
        template_id: int,
        newid: int,
        name: str,
        storage: Optional[str],
        full_clone: bool,
        wait: bool = True,
    ) -> None:
        """Clone một template thành VM mới (newid)."""
        params = {
            "newid": newid,
            "name": name,
            "full": 1 if full_clone else 0,
        }
        if storage:
            params["storage"] = storage
        try:
            upid = self._api.nodes(node).qemu(template_id).clone.post(**params)
        except ResourceException as exc:
            raise ProxmoxError(f"Clone template {template_id} thất bại: {exc}", 400) from exc
        if wait:
            self.wait_for_task(node, upid)

    def configure_vm(
        self,
        node: str,
        vmid: int,
        cores: int,
        memory_mb: int,
        bridge: str,
        ci_user: Optional[str] = None,
        ci_password: Optional[str] = None,
        ssh_public_key: Optional[str] = None,
        ip_address: Optional[str] = None,
        gateway: Optional[str] = None,
        nameserver: Optional[str] = None,
        cicustom: Optional[str] = None,
    ) -> None:
        """Cấu hình CPU/RAM/mạng/cloud-init cho VM.

        Nếu `cicustom` được cung cấp (user-data riêng của VPS), dùng nó thay cho
        ciuser/cipassword/sshkeys native — đảm bảo tạo user + sudo độc lập, đáng tin cậy.
        """
        params: dict = {
            "cores": cores,
            "memory": memory_mb,
            "net0": f"virtio,bridge={bridge}",
        }
        if cicustom:
            # user-data tuỳ biến (tạo user/pass + sudo). Network vẫn dùng ipconfig0 bên dưới.
            params["cicustom"] = cicustom
        else:
            if ci_user:
                params["ciuser"] = ci_user
            if ci_password:
                params["cipassword"] = ci_password
            if ssh_public_key:
                # sshkeys phải được URL-encode khi gửi cho Proxmox.
                params["sshkeys"] = urllib.parse.quote(ssh_public_key.strip(), safe="")
        if nameserver:
            params["nameserver"] = nameserver

        # Cấu hình IP qua cloud-init (ipconfig0)
        if ip_address:
            ipconfig = f"ip={ip_address}"
            if gateway:
                ipconfig += f",gw={gateway}"
            params["ipconfig0"] = ipconfig
        else:
            params["ipconfig0"] = "ip=dhcp"

        try:
            self._api.nodes(node).qemu(vmid).config.post(**params)
        except ResourceException as exc:
            raise ProxmoxError(f"Cấu hình VM {vmid} thất bại: {exc}", 400) from exc

    def resize_disk(self, node: str, vmid: int, disk_gb: int, disk: str = "scsi0") -> None:
        """Tăng dung lượng disk lên disk_gb (GB). Chỉ tăng, không giảm được."""
        try:
            self._api.nodes(node).qemu(vmid).resize.put(disk=disk, size=f"{disk_gb}G")
        except ResourceException as exc:
            raise ProxmoxError(
                f"Resize disk {disk} của VM {vmid} thất bại "
                f"(disk '{disk}' có thể không tồn tại, hoặc size nhỏ hơn template): {exc}",
                400,
            ) from exc

    def start_vm(self, node: str, vmid: int, wait: bool = True) -> None:
        try:
            upid = self._api.nodes(node).qemu(vmid).status.start.post()
        except ResourceException as exc:
            raise ProxmoxError(f"Khởi động VM {vmid} thất bại: {exc}", 400) from exc
        if wait:
            self.wait_for_task(node, upid)

    def stop_vm(self, node: str, vmid: int, wait: bool = True) -> None:
        try:
            upid = self._api.nodes(node).qemu(vmid).status.stop.post()
        except ResourceException as exc:
            raise ProxmoxError(f"Dừng VM {vmid} thất bại: {exc}", 400) from exc
        if wait:
            self.wait_for_task(node, upid)

    def delete_vm(self, node: str, vmid: int, wait: bool = True) -> None:
        try:
            upid = self._api.nodes(node).qemu(vmid).delete(purge=1)
        except ResourceException as exc:
            raise ProxmoxError(f"Xoá VM {vmid} thất bại: {exc}", 400) from exc
        if wait:
            self.wait_for_task(node, upid)

    def get_vm_status(self, node: str, vmid: int) -> dict:
        try:
            return self._api.nodes(node).qemu(vmid).status.current.get()
        except ResourceException as exc:
            raise ProxmoxError(f"Không lấy được trạng thái VM {vmid}: {exc}", 404) from exc

    def list_vms(self, node: str) -> list[dict]:
        try:
            return self._api.nodes(node).qemu.get()
        except ResourceException as exc:
            raise ProxmoxError(f"Không liệt kê được VM trên node {node}: {exc}", 502) from exc

    def get_vm_config(self, node: str, vmid: int) -> dict:
        """Cấu hình tĩnh của VM (cores, memory, scsi0, net0, ipconfig0, ostype...)."""
        try:
            return self._api.nodes(node).qemu(vmid).config.get()
        except ResourceException as exc:
            raise ProxmoxError(f"Không lấy được cấu hình VM {vmid}: {exc}", 404) from exc

    # ----- Console (Shell/serial qua xterm.js) -----

    def open_term_console(self, node: str, vmid: int) -> dict:
        """Mở phiên serial/xterm console cho VM, trả bộ ticket để client mở websocket.

        Dùng API token (đã kiểm chứng chạy trên PVE 9.2 cho cả `termproxy` lẫn
        websocket `vncwebsocket`). Login-ticket bằng mật khẩu KHÔNG dùng được vì
        root@pam bật 2FA.

        Trả về: node, vmid, port, ticket (vncticket), user, auth_header.
        `auth_header` là chuỗi `Authorization` (PVEAPIToken=...) mà Node BFF dùng cho
        websocket upgrade — GIỮ PHÍA SERVER, không đẩy ra trình duyệt. Client chỉ cần
        `user` + `ticket` cho thông điệp xác thực đầu tiên của giao thức xterm.
        """
        s = self._settings
        try:
            data = self._api.nodes(node).qemu(vmid).termproxy.post()
        except ResourceException as exc:
            raise ProxmoxError(
                f"Mở termproxy cho VM {vmid} thất bại (VM có serial console không?): {exc}",
                502,
            ) from exc
        if not data.get("ticket") or not data.get("port"):
            raise ProxmoxError("termproxy không trả về ticket/port hợp lệ.", 502)

        auth_header = f"PVEAPIToken={s.proxmox_user}!{s.proxmox_token_name}={s.proxmox_token_value}"
        return {
            "node": node,
            "vmid": vmid,
            "port": int(data["port"]),
            "ticket": data["ticket"],
            "user": data.get("user", f"{s.proxmox_user}!{s.proxmox_token_name}"),
            "auth_header": auth_header,
        }
