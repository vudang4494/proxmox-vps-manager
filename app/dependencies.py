"""Dependency injection cho FastAPI: settings, client, service, auth."""

from functools import lru_cache

from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings
from .proxmox_client import ProxmoxClient
from .services import VPSService


@lru_cache
def _get_client() -> ProxmoxClient:
    """Singleton ProxmoxClient (tái dùng session HTTP cho mọi request)."""
    return ProxmoxClient(get_settings())


def get_service() -> VPSService:
    settings = get_settings()
    return VPSService(_get_client(), settings)


def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    """Kiểm tra header X-API-Key. Nếu API_KEY rỗng thì bỏ qua auth."""
    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key không hợp lệ hoặc thiếu.",
        )
