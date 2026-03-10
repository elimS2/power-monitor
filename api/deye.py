"""Deye inverter API routes."""
import logging

from fastapi import APIRouter, Query, Request, HTTPException

from api.deps import check_key
from database import save_deye_log

router = APIRouter(tags=["deye"])
log = logging.getLogger(__name__)


@router.post("/api/deye-heartbeat")
async def ep_deye_heartbeat(request: Request, key: str = Query("")):
    """Receive Deye inverter data from local script. Requires API key."""
    try:
        check_key(key)
        data = await request.json()
        save_deye_log(
            load_power_w=data.get("load_power_w"),
            load_l1_w=data.get("load_l1_w"),
            load_l2_w=data.get("load_l2_w"),
            load_l3_w=data.get("load_l3_w"),
            grid_power_w=data.get("grid_power_w"),
            grid_v_l1=data.get("grid_v_l1"),
            grid_v_l2=data.get("grid_v_l2"),
            grid_v_l3=data.get("grid_v_l3"),
            battery_soc=data.get("battery_soc"),
            battery_power_w=data.get("battery_power_w"),
            battery_voltage=data.get("battery_voltage"),
            day_load_kwh=data.get("day_load_kwh"),
            total_load_kwh=data.get("total_load_kwh"),
            month_load_kwh=data.get("month_load_kwh"),
            year_load_kwh=data.get("year_load_kwh"),
            day_grid_import_kwh=data.get("day_grid_import_kwh"),
            day_grid_export_kwh=data.get("day_grid_export_kwh"),
            total_grid_import_kwh=data.get("total_grid_import_kwh"),
            total_grid_export_kwh=data.get("total_grid_export_kwh"),
        )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("deye-heartbeat failed")
        raise HTTPException(status_code=500, detail=str(e))
