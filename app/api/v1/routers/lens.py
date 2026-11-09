"""Cross-company lenses (ADR 0007 layer 3). Gated: a cache miss calls SEC
XBRL and the LLM."""
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import require_shared_secret
from app.schemas.lens import LensReport, LensSummary
from app.services.lens import get_lens, list_lenses

router = APIRouter(dependencies=[Depends(require_shared_secret)])


@router.get("/lens", response_model=list[LensSummary])
async def lens_index() -> list[LensSummary]:
    return list_lenses()


@router.get("/lens/{lens_id}", response_model=LensReport)
async def lens_detail(lens_id: str) -> LensReport:
    try:
        report = await get_lens(lens_id)
    except Exception as exc:  # SEC or provider down with nothing cached
        raise HTTPException(status_code=503, detail="Lens data is unavailable right now; try again shortly.") from exc
    if report is None:
        raise HTTPException(status_code=404, detail=f"Unknown lens {lens_id!r}")
    return report
