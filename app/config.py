"""Cấu hình ứng dụng, nạp từ biến môi trường / file .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Kết nối Proxmox
    proxmox_host: str
    proxmox_port: int = 8006
    proxmox_user: str = "root@pam"
    proxmox_token_name: str
    proxmox_token_value: str
    proxmox_verify_ssl: bool = False

    # Mặc định khi tạo VPS
    default_node: str = "pve"
    default_template_id: int = 9000
    default_storage: str = "local-lvm"
    default_bridge: str = "vmbr0"

    # Cloud-init user-data riêng cho từng VPS (để tạo user/pass + sudo độc lập).
    # FastAPI chạy trên host nên ghi snippet trực tiếp vào thư mục snippets của Proxmox.
    # Yêu cầu storage `snippets_storage` đã bật content `snippets`
    # (chạy 1 lần: pvesm set local --content iso,vztmpl,backup,import,snippets).
    snippets_storage: str = "local"
    snippets_dir: str = "/var/lib/vz/snippets"

    # Bảo mật API của service này
    api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    """Trả về singleton Settings (cache để khỏi đọc .env nhiều lần)."""
    return Settings()
