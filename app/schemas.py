"""Pydantic models cho request/response."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CreateVPSRequest(BaseModel):
    """Tham số tạo một VPS mới bằng cách clone template."""

    name: str = Field(..., description="Tên hostname của VM", examples=["web-01"])
    cores: int = Field(2, ge=1, le=128, description="Số vCPU")
    memory_mb: int = Field(2048, ge=128, description="RAM tính bằng MB")
    disk_gb: Optional[int] = Field(
        None,
        ge=1,
        description="Dung lượng disk (GB). Phải >= disk của template. Bỏ trống = giữ nguyên template.",
    )

    # Cloud-init
    ci_user: Optional[str] = Field(None, description="User cloud-init tạo trong VM")
    ci_password: Optional[str] = Field(None, description="Mật khẩu cho ci_user")
    ssh_public_key: Optional[str] = Field(
        None, description="SSH public key (nội dung), nạp vào authorized_keys"
    )

    # Mạng (cloud-init ipconfig0). Bỏ trống ip_address = dùng DHCP.
    ip_address: Optional[str] = Field(
        None,
        description="IP/CIDR tĩnh, vd 192.168.1.50/24. Bỏ trống = DHCP.",
        examples=["192.168.1.50/24"],
    )
    gateway: Optional[str] = Field(None, description="Default gateway", examples=["192.168.1.1"])
    nameserver: Optional[str] = Field(None, description="DNS server", examples=["1.1.1.1"])

    # Override mặc định trong .env (tuỳ chọn)
    node: Optional[str] = Field(None, description="Node Proxmox. Bỏ trống = DEFAULT_NODE.")
    template_id: Optional[int] = Field(
        None, description="VMID template để clone. Bỏ trống = DEFAULT_TEMPLATE_ID."
    )
    storage: Optional[str] = Field(None, description="Storage cho disk. Bỏ trống = DEFAULT_STORAGE.")
    bridge: Optional[str] = Field(None, description="Network bridge. Bỏ trống = DEFAULT_BRIDGE.")

    full_clone: bool = Field(True, description="True = full clone (độc lập), False = linked clone.")
    start: bool = Field(True, description="Bật VM ngay sau khi tạo.")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name không được rỗng")
        # Proxmox/cloud-init hostname: chữ, số, dấu gạch ngang
        if not all(c.isalnum() or c == "-" for c in v):
            raise ValueError("name chỉ được chứa chữ, số và dấu '-'")
        return v

    @field_validator("ci_user")
    @classmethod
    def validate_ci_user(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        # username Linux an toàn (được nhúng vào cloud-init YAML + lệnh shell)
        import re as _re

        if not _re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", v):
            raise ValueError(
                "ci_user phải là username Linux hợp lệ: bắt đầu bằng chữ thường/'_', "
                "chỉ gồm chữ thường, số, '-', '_' (tối đa 32 ký tự)"
            )
        return v


class VPSInfo(BaseModel):
    """Thông tin trạng thái một VM."""

    vmid: int
    name: Optional[str] = None
    node: str
    status: str = Field(..., description="running | stopped | ...")
    cores: Optional[int] = None
    memory_mb: Optional[int] = None
    uptime: Optional[int] = None


class VPSDetail(BaseModel):
    """Thông tin chi tiết VM (gộp config tĩnh + trạng thái runtime) để hiển thị trực quan."""

    vmid: int
    name: Optional[str] = None
    node: str
    status: str
    cores: Optional[int] = None
    memory_mb: Optional[int] = None
    disk_gb: Optional[float] = None
    ip_config: Optional[str] = Field(None, description="ipconfig0 (cloud-init), vd ip=dhcp")
    bridge: Optional[str] = None
    ostype: Optional[str] = None
    uptime: Optional[int] = None


class ConsoleTicket(BaseModel):
    """Bộ ticket mở Shell Console qua websocket Proxmox.

    `auth_header` (PVEAPIToken=...) là bí mật — chỉ dùng phía Node BFF cho websocket
    upgrade, KHÔNG đẩy ra trình duyệt.
    """

    node: str
    vmid: int
    port: int
    ticket: str = Field(..., description="vncticket cho thông điệp xác thực đầu tiên")
    user: str
    auth_header: str = Field(..., description="Authorization (PVEAPIToken) — server-side cho WS upgrade")


class CreateVPSResponse(BaseModel):
    vmid: int
    name: str
    node: str
    status: str
    message: str
