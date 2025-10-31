from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.get("/reports/daily/latest")
async def latest_report():
    raise HTTPException(status_code=501, detail="Not implemented in Story 1")
