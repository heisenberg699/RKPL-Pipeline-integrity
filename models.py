"""
integrity_reco.models
=====================
Defect data model for the RKPL repair-recommendation module.

Units convention (SI, consistent throughout):
    - Lengths / dimensions : mm
    - Pressure             : MPa (1 kg/cm2 = 0.0980665 MPa)
    - Stress (SMYS)        : MPa

If your existing rkpl_health schema differs, map your fields into
`DefectRecord` at the import boundary — nothing downstream needs to change.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class DefectType(str, Enum):
    EXTERNAL_METAL_LOSS = "external_metal_loss"
    INTERNAL_METAL_LOSS = "internal_metal_loss"
    PITTING = "pitting"                      # localised, L ~ W ~ small
    AXIAL_GROOVING = "axial_grooving"
    CIRCUMFERENTIAL_GROOVING = "circumferential_grooving"


class LeakStatus(str, Enum):
    NON_LEAKING = "non_leaking"
    LEAKING = "leaking"


class PipeSpec(BaseModel):
    """Line-pipe parameters for the segment containing the defect."""
    outside_diameter_mm: float = Field(..., gt=0, description="Nominal OD, mm")
    wall_thickness_mm: float = Field(..., gt=0, description="Nominal wall thickness, mm")
    smys_mpa: float = Field(..., gt=0, description="Specified Minimum Yield Strength, MPa")
    maop_mpa: float = Field(..., gt=0, description="Maximum Allowable Operating Pressure, MPa")
    design_factor: float = Field(
        0.72, gt=0, le=1.0,
        description="Design factor F per ASME B31.4 (liquid pipelines: 0.72)",
    )

    @field_validator("wall_thickness_mm")
    @classmethod
    def _wt_lt_od(cls, v, info):
        od = info.data.get("outside_diameter_mm")
        if od is not None and v >= od / 2:
            raise ValueError("wall thickness must be < OD/2")
        return v


class DefectRecord(BaseModel):
    """
    One metal-loss defect, from ILI vendor listing or manual field entry.

    ILI CSV column mapping (typical vendor pigging report):
        log_distance_m   <- "Log Dist. [m]" / odometer
        depth_pct        <- "Depth [%]" (percent of wall thickness)
        length_mm        <- "Length [mm]" (axial extent)
        width_mm         <- "Width [mm]" (circumferential extent, optional)
        orientation_oclock <- "O'clock"
    """
    defect_id: str
    defect_type: DefectType
    log_distance_m: Optional[float] = Field(None, description="ILI odometer chainage, m")
    depth_pct: float = Field(..., ge=0, le=100, description="Max depth as % of nominal WT")
    length_mm: float = Field(..., gt=0, description="Axial length of metal loss, mm")
    width_mm: Optional[float] = Field(None, gt=0)
    orientation_oclock: Optional[str] = None
    leak_status: LeakStatus = LeakStatus.NON_LEAKING
    interacting: bool = Field(
        False,
        description=(
            "True if within interaction spacing of another defect "
            "(flag from ILI vendor or field UT). Interacting defects are "
            "outside B31G Level-1 scope -> escalated to Level-2/API 579."
        ),
    )
    near_weld: bool = Field(
        False,
        description="Within 25 mm of a girth/seam weld (field verification needed).",
    )
    field_verified: bool = Field(
        False,
        description="Depth/length confirmed by direct UT/pit-gauge measurement.",
    )
    source: str = Field("manual", description="'ili' or 'manual'")

    @property
    def depth_fraction(self) -> float:
        return self.depth_pct / 100.0
