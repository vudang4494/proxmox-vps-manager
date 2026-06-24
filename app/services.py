"""Nghiệp vụ cấp VPS: ghép các thao tác Proxmox thành luồng hoàn chỉnh."""

import logging
import os
import re

from .config import Settings
from .proxmox_client import ProxmoxClient, ProxmoxError
from .schemas import (
    ConsoleTicket,
    CreateVPSRequest,
    CreateVPSResponse,
    VPSDetail,
    VPSInfo,
)


def _parse_disk_gb(*disk_specs: str | None) -> float | None:
    """Đọc 'size=100G' từ một dòng cấu hình disk (scsi0/virtio0/...) -> GB."""
    for spec in disk_specs:
        if not spec:
            continue
        m = re.search(r"size=(\d+(?:\.\d+)?)([KMGT])", spec)
        if not m:
            continue
        val, unit = float(m.group(1)), m.group(2)
        factor = {"K": 1 / 1024 / 1024, "M": 1 / 1024, "G": 1, "T": 1024}[unit]
        return round(val * factor, 1)
    return None


def _parse_bridge(net0: str | None) -> str | None:
    """Đọc 'bridge=vmbr0' từ net0."""
    if not net0:
        return None
    m = re.search(r"bridge=([^,]+)", net0)
    return m.group(1) if m else None


def _yaml_sq(s: str) -> str:
    """Bọc chuỗi trong nháy đơn YAML an toàn (escape ' thành '')."""
    return "'" + s.replace("'", "''") + "'"


def build_cloudinit_userdata(
    name: str,
    ci_user: str,
    ci_password: str | None,
    ssh_public_key: str | None = None,
) -> str:
    """Sinh cloud-init user-data RIÊNG cho 1 VPS: tạo user, mở khoá, cấp NOPASSWD sudo.

    Dùng schema hiện đại `users:` + `chpasswd.users` (đáng tin cậy, khác combo legacy
    `user:`+`users:[default]` của Proxmox vốn không tạo được user). Kèm `runcmd` dự phòng
    bảo đảm user tồn tại + có sudo kể cả khi module users gặp trục trặc.
    """
    lines = [
        "#cloud-config",
        f"hostname: {name}",
        "manage_etc_hosts: true",
        "ssh_pwauth: true",
        "users:",
        f"  - name: {ci_user}",
        "    lock_passwd: false",
        "    shell: /bin/bash",
        "    groups: [sudo, adm]",
        "    sudo: 'ALL=(ALL) NOPASSWD:ALL'",
    ]
    if ssh_public_key and ssh_public_key.strip():
        lines.append("    ssh_authorized_keys:")
        lines.append(f"      - {_yaml_sq(ssh_public_key.strip())}")
    if ci_password:
        lines += [
            "chpasswd:",
            "  expire: false",
            "  users:",
            f"    - {{name: {ci_user}, password: {_yaml_sq(ci_password)}, type: text}}",
            # Dự phòng: ghi 'user:pass' ra file (chỉ escape YAML, không shell) để runcmd nạp.
            "write_files:",
            "  - path: /run/vpscred",
            "    permissions: '0600'",
            f"    content: {_yaml_sq(ci_user + ':' + ci_password)}",
        ]
    # runcmd dự phòng: bảo đảm user tồn tại + có sudo + (đặt lại password từ file).
    runcmd = [
        "runcmd:",
        f"  - id {ci_user} >/dev/null 2>&1 || useradd -m -s /bin/bash {ci_user}",
        f"  - usermod -aG sudo {ci_user} || true",
        f"  - printf '%s ALL=(ALL) NOPASSWD:ALL\\n' {ci_user} > /etc/sudoers.d/90-{ci_user}",
        f"  - chmod 440 /etc/sudoers.d/90-{ci_user}",
    ]
    if ci_password:
        runcmd += [
            "  - chpasswd < /run/vpscred",
            "  - rm -f /run/vpscred",
        ]
    lines += runcmd
    return "\n".join(lines) + "\n"

logger = logging.getLogger("proxmox.vps")


class VPSService:
    def __init__(self, client: ProxmoxClient, settings: Settings):
        self.client = client
        self.settings = settings

    def create_vps(self, req: CreateVPSRequest) -> CreateVPSResponse:
        node = req.node or self.settings.default_node
        template_id = req.template_id or self.settings.default_template_id
        storage = req.storage or self.settings.default_storage
        bridge = req.bridge or self.settings.default_bridge

        vmid = self.client.next_vmid()
        logger.info("Tạo VPS '%s' -> VMID %s trên node %s (clone từ %s)", req.name, vmid, node, template_id)

        # 1) Clone template (chờ task xong)
        self.client.clone_template(
            node=node,
            template_id=template_id,
            newid=vmid,
            name=req.name,
            storage=storage,
            full_clone=req.full_clone,
        )

        # Nếu các bước sau lỗi, dọn dẹp VM vừa clone để không để rác.
        try:
            # 2) Cloud-init: nếu có ci_user → sinh user-data RIÊNG cho VPS này (user/pass + sudo,
            #    độc lập hoàn toàn với user Proxmox) và gắn qua cicustom.
            cicustom = None
            if req.ci_user:
                userdata = build_cloudinit_userdata(
                    req.name, req.ci_user, req.ci_password, req.ssh_public_key
                )
                cicustom = self._write_snippet(vmid, userdata)

            # 3) Cấu hình CPU/RAM/mạng/cloud-init
            self.client.configure_vm(
                node=node,
                vmid=vmid,
                cores=req.cores,
                memory_mb=req.memory_mb,
                bridge=bridge,
                ci_user=req.ci_user,
                ci_password=req.ci_password,
                ssh_public_key=req.ssh_public_key,
                ip_address=req.ip_address,
                gateway=req.gateway,
                nameserver=req.nameserver,
                cicustom=cicustom,
            )

            # 3) Resize disk nếu yêu cầu
            if req.disk_gb:
                self.client.resize_disk(node=node, vmid=vmid, disk_gb=req.disk_gb)

            # 4) Bật VM nếu yêu cầu
            status = "stopped"
            if req.start:
                self.client.start_vm(node=node, vmid=vmid)
                status = "running"
        except ProxmoxError:
            logger.exception("Lỗi khi cấu hình VMID %s — đang rollback (xoá VM)", vmid)
            self._safe_cleanup(node, vmid)
            raise

        return CreateVPSResponse(
            vmid=vmid,
            name=req.name,
            node=node,
            status=status,
            message=f"VPS '{req.name}' đã được tạo thành công với VMID {vmid}.",
        )

    def _safe_cleanup(self, node: str, vmid: int) -> None:
        """Cố gắng xoá VM lỗi; nuốt lỗi để không che mất lỗi gốc."""
        try:
            if self.client.vm_exists(node, vmid):
                self.client.delete_vm(node, vmid)
        except Exception:  # noqa: BLE001 - best effort cleanup
            logger.warning("Không rollback được VMID %s, cần dọn thủ công", vmid)
        self._remove_snippet(vmid)

    # ----- Cloud-init snippet (user-data riêng từng VPS) -----

    def _snippet_path(self, vmid: int) -> str:
        return os.path.join(self.settings.snippets_dir, f"vps-{vmid}.yaml")

    def _write_snippet(self, vmid: int, content: str) -> str:
        """Ghi user-data ra thư mục snippets của Proxmox, trả về giá trị cho `cicustom`."""
        try:
            os.makedirs(self.settings.snippets_dir, exist_ok=True)
            path = self._snippet_path(vmid)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(path, 0o600)
        except OSError as exc:
            raise ProxmoxError(
                f"Không ghi được cloud-init snippet ({exc}). Đã bật content 'snippets' cho "
                f"storage '{self.settings.snippets_storage}' chưa? "
                f"(pvesm set {self.settings.snippets_storage} --content ...,snippets)",
                500,
            ) from exc
        return f"user={self.settings.snippets_storage}:snippets/vps-{vmid}.yaml"

    def _remove_snippet(self, vmid: int) -> None:
        try:
            os.remove(self._snippet_path(vmid))
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("Không xoá được snippet của VMID %s", vmid)

    def get_vps(self, vmid: int, node: str | None = None) -> VPSInfo:
        node = node or self.settings.default_node
        data = self.client.get_vm_status(node, vmid)
        return VPSInfo(
            vmid=vmid,
            name=data.get("name"),
            node=node,
            status=data.get("status", "unknown"),
            cores=data.get("cpus"),
            memory_mb=int(data["maxmem"] / 1024 / 1024) if data.get("maxmem") else None,
            uptime=data.get("uptime"),
        )

    def list_vps(self, node: str | None = None) -> list[VPSInfo]:
        node = node or self.settings.default_node
        out: list[VPSInfo] = []
        for vm in self.client.list_vms(node):
            out.append(
                VPSInfo(
                    vmid=int(vm["vmid"]),
                    name=vm.get("name"),
                    node=node,
                    status=vm.get("status", "unknown"),
                    cores=vm.get("cpus"),
                    memory_mb=int(vm["maxmem"] / 1024 / 1024) if vm.get("maxmem") else None,
                    uptime=vm.get("uptime"),
                )
            )
        return out

    def get_detail(self, vmid: int, node: str | None = None) -> VPSDetail:
        """Gộp config tĩnh + trạng thái runtime của một VM để hiển thị chi tiết."""
        node = node or self.settings.default_node
        status = self.client.get_vm_status(node, vmid)
        cfg = self.client.get_vm_config(node, vmid)
        memory_mb = cfg.get("memory")
        if memory_mb is None and status.get("maxmem"):
            memory_mb = int(status["maxmem"] / 1024 / 1024)
        return VPSDetail(
            vmid=vmid,
            name=cfg.get("name") or status.get("name"),
            node=node,
            status=status.get("status", "unknown"),
            cores=cfg.get("cores") or status.get("cpus"),
            memory_mb=int(memory_mb) if memory_mb else None,
            disk_gb=_parse_disk_gb(cfg.get("scsi0"), cfg.get("virtio0"), cfg.get("sata0")),
            ip_config=cfg.get("ipconfig0"),
            bridge=_parse_bridge(cfg.get("net0")),
            ostype=cfg.get("ostype"),
            uptime=status.get("uptime"),
        )

    def open_console(self, vmid: int, node: str | None = None) -> ConsoleTicket:
        """Mở Shell Console (serial/xterm) cho VM, trả bộ ticket cho websocket."""
        node = node or self.settings.default_node
        # Xác nhận VM tồn tại (raise 404 nếu không) trước khi mở console.
        self.client.get_vm_status(node, vmid)
        bundle = self.client.open_term_console(node, vmid)
        return ConsoleTicket(**bundle)

    def delete_vps(self, vmid: int, node: str | None = None) -> None:
        node = node or self.settings.default_node
        # Phải dừng trước khi xoá nếu đang chạy.
        data = self.client.get_vm_status(node, vmid)
        if data.get("status") == "running":
            self.client.stop_vm(node, vmid)
        self.client.delete_vm(node, vmid)
        self._remove_snippet(vmid)

    def power_action(self, vmid: int, action: str, node: str | None = None) -> str:
        node = node or self.settings.default_node
        if action == "start":
            self.client.start_vm(node, vmid)
            return "running"
        if action == "stop":
            self.client.stop_vm(node, vmid)
            return "stopped"
        raise ProxmoxError(f"Hành động không hợp lệ: {action}", 400)
