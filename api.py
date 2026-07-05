"""
integrity_reco.api
==================
FastAPI router — mount into your existing rkpl_health app:

    from integrity_reco.api import router as reco_router
    app.include_router(reco_router, prefix="/integrity", tags=["repair-reco"])

Endpoints:
    POST /integrity/assess          one defect -> full recommendation card
    POST /integrity/assess-csv      ILI CSV upload -> list of cards + row errors
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from .models import DefectRecord, PipeSpec
from .recommend import parse_ili_csv, recommend

router = APIRouter()


class AssessRequest(BaseModel):
    defect: DefectRecord
    pipe: PipeSpec


@router.post("/assess")
def assess(req: AssessRequest) -> dict:
    return recommend(req.defect, req.pipe)


class CsvAssessResponse(BaseModel):
    cards: list[dict]
    row_errors: list[str]


@router.post("/assess-csv", response_model=CsvAssessResponse)
async def assess_csv(pipe: str, file: UploadFile = File(...)) -> CsvAssessResponse:
    """`pipe` is a JSON string of PipeSpec (multipart form limitation)."""
    try:
        pipe_spec = PipeSpec.model_validate_json(pipe)
    except Exception as e:
        raise HTTPException(422, f"Invalid pipe spec: {e}")
    text = (await file.read()).decode("utf-8-sig")
    records, errors = parse_ili_csv(text)
    cards = [recommend(r, pipe_spec) for r in records]
    return CsvAssessResponse(cards=cards, row_errors=errors)
