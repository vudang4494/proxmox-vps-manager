"""REST endpoints cho việc quản lý VPS."""

from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from ..dependencies import get_service, verify_api_key
from ..schemas import ConsoleTicket, CreateVPSRequest, CreateVPSResponse, VPSDetail, VPSInfo
from ..services import VPSService

router = APIRouter(
    prefix="/api/v1/vps",
    tags=["vps"],
    dependencies=[Depends(verify_api_key)],
)


# Các route gọi Proxmox đều khai báo `def` (không async) để FastAPI chạy
# trong threadpool, tránh block event loop vì proxmoxer là blocking I/O.


@router.post(
    "",
    response_model=CreateVPSResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo VPS mới (clone template)",
)
def create_vps(req: CreateVPSRequest, service: VPSService = Depends(get_service)):
    return service.create_vps(req)


@router.get("", response_model=list[VPSInfo], summary="Liệt kê VPS trên một node")
def list_vps(
    node: Optional[str] = Query(None, description="Node Proxmox. Bỏ trống = DEFAULT_NODE."),
    service: VPSService = Depends(get_service),
):
    return service.list_vps(node)


@router.get("/{vmid}", response_model=VPSInfo, summary="Xem trạng thái một VPS")
def get_vps(
    vmid: int,
    node: Optional[str] = Query(None),
    service: VPSService = Depends(get_service),
):
    return service.get_vps(vmid, node)


@router.get("/{vmid}/detail", response_model=VPSDetail, summary="Chi tiết cấu hình + trạng thái VPS")
def detail_vps(
    vmid: int,
    node: Optional[str] = Query(None),
    service: VPSService = Depends(get_service),
):
    return service.get_detail(vmid, node)


@router.post(
    "/{vmid}/console",
    response_model=ConsoleTicket,
    summary="Mở Shell Console (serial/xterm) — trả ticket cho websocket",
)
def console_vps(
    vmid: int,
    node: Optional[str] = Query(None),
    service: VPSService = Depends(get_service),
):
    return service.open_console(vmid, node)


@router.post("/{vmid}/start", response_model=VPSInfo, summary="Bật VPS")
def start_vps(
    vmid: int,
    node: Optional[str] = Query(None),
    service: VPSService = Depends(get_service),
):
    service.power_action(vmid, "start", node)
    return service.get_vps(vmid, node)


@router.post("/{vmid}/stop", response_model=VPSInfo, summary="Tắt VPS")
def stop_vps(
    vmid: int,
    node: Optional[str] = Query(None),
    service: VPSService = Depends(get_service),
):
    service.power_action(vmid, "stop", node)
    return service.get_vps(vmid, node)


@router.delete("/{vmid}", status_code=status.HTTP_204_NO_CONTENT, summary="Xoá VPS")
def delete_vps(
    vmid: int,
    node: Optional[str] = Query(None),
    service: VPSService = Depends(get_service),
):
    service.delete_vps(vmid, node)
