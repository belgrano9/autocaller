from fastapi import APIRouter, HTTPException
import app.services.email_provider as provider

router = APIRouter(prefix="/mode", tags=["mode"])

VALID = {"dev", "int"}


@router.get("")
def get_mode():
    return {"mode": provider.current_mode}


@router.post("/{mode}")
def set_mode(mode: str):
    if mode not in VALID:
        raise HTTPException(status_code=400, detail=f"mode must be one of {VALID}")
    provider.current_mode = mode
    return {"mode": provider.current_mode}
