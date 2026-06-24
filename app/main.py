"""Điểm khởi tạo ứng dụng FastAPI."""

import logging

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from .proxmox_client import ProxmoxError
from .routers import vps

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="Proxmox VPS API",
    version=__version__,
    description="API tự động tạo và quản lý VPS (KVM) trên Proxmox bằng cách clone template.",
)


@app.exception_handler(ProxmoxError)
async def proxmox_error_handler(_: Request, exc: ProxmoxError):
    """Chuyển lỗi nghiệp vụ Proxmox thành HTTP response gọn gàng."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(requests.exceptions.Timeout)
async def proxmox_timeout_handler(_: Request, exc: requests.exceptions.Timeout):
    """Proxmox phản hồi quá chậm / timeout kết nối."""
    logging.getLogger("proxmox").warning("Timeout khi gọi Proxmox: %s", exc)
    return JSONResponse(
        status_code=504, content={"detail": "Proxmox phản hồi quá thời gian (timeout)."}
    )


@app.exception_handler(requests.exceptions.RequestException)
async def proxmox_connection_handler(_: Request, exc: requests.exceptions.RequestException):
    """Không kết nối được tới Proxmox (host sai, mạng lỗi, cổng đóng...)."""
    logging.getLogger("proxmox").warning("Không kết nối được Proxmox: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Không kết nối được tới Proxmox. Kiểm tra PROXMOX_HOST/cổng/mạng."},
    )


@app.get("/health", tags=["system"], summary="Health check")
def health():
    return {"status": "ok", "version": __version__}


app.include_router(vps.router)
