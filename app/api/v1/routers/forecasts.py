from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.get("/forecasts/{symbol}")
async def get_forecast(symbol: str):
    raise HTTPException(status_code=501, detail="Not implemented in Story 1")
