from fastapi import APIRouter, HTTPException


router = APIRouter()


def _ni():
    raise HTTPException(status_code=501, detail="Not implemented in Story 1")


@router.post("/analyze")
async def analyze():
    _ni()


@router.get("/reports/daily/latest")
async def latest_report():
    _ni()


@router.get("/reports/daily/{date}")
async def report_by_date(date: str):
    _ni()


@router.get("/forecast/{symbol}")
async def forecast(symbol: str):
    _ni()


@router.post("/strategy/generate")
async def strategy_generate():
    _ni()