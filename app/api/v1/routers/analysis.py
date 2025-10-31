from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.post("/analysis")
async def analyze():
    raise HTTPException(status_code=501, detail="Not implemented in Story 1")
