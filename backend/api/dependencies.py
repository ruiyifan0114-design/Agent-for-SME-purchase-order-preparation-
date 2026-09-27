from secrets import compare_digest
from fastapi import Depends, Header
from backend.config import settings
from backend.db.session import get_session
from backend.tools.procurement import ProcurementTools
from backend.tools.runtime import BusinessError


def principal(x_api_key: str = Header(default="")):
    cfg = settings()
    if cfg.api_key == cfg.reviewer_api_key:
        raise BusinessError("Service and reviewer credentials must differ", "CONFIGURATION_ERROR", 503)
    if x_api_key and compare_digest(x_api_key, cfg.reviewer_api_key):
        return {"actor": cfg.reviewer_name, "human": True}
    if x_api_key and compare_digest(x_api_key, cfg.api_key):
        return {"actor": "procurement-service", "human": False}
    raise BusinessError("Valid X-API-Key required", "UNAUTHORIZED", 401)


def tools(db=Depends(get_session), identity=Depends(principal)):
    return ProcurementTools(db, **identity)
