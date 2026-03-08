"""Deye inverter API routes."""
from fastapi import APIRouter, Query, Request

from api.deps import check_key
from database import save_deye_log

router = APIRouter(tags=["deye"])


@router.post("/api/deye-heartbeat")
async def ep_deye_heartbeat(request: Request, key: str = Query("")):
    """Receive Deye inverter data from local script. Requires API key."""
    check_key(key)
    data = await request.json()
    save_deye_log(
        load_power_w=data.get("load_power_w"),
        load_l1_w=data.get("load_l1_w"),
        load_l2_w=data.get("load_l2_w"),
        load_l3_w=data.get("load_l3_w"),
        grid_v_l1=data.get("grid_v_l1"),
        grid_v_l2=data.get("grid_v_l2"),
        grid_v_l3=data.get("grid_v_l3"),
        battery_soc=data.get("battery_soc"),
        battery_power_w=data.get("battery_power_w"),
        battery_voltage=data.get("battery_voltage"),
    )
    return {"ok": True}
