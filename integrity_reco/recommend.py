"""
integrity_reco.recommend
========================
Orchestrator: defect + pipe -> assessment (both B31G methods) ->
governing result -> permitted repair options -> SOP checklist.

The governing result is the MORE CONSERVATIVE of the two Level-1 methods
(higher ERF / worse disposition), unless the user explicitly selects one.
Everything in the output is either a computed number, a static catalogue
row, or a static SOP item — no generated prose.
"""

from __future__ import annotations

import csv
import io
from dataclasses import asdict
from typing import Any

from .b31g import AssessmentResult, Disposition, assess_both
from .models import DefectRecord, DefectType, LeakStatus, PipeSpec
from .repair_rules import (RULES_VERSION, SOPItem, build_sop_checklist,
                           select_repair_options)

_SEVERITY = {
    Disposition.ACCEPTABLE_MONITOR: 0,
    Disposition.ACCEPTABLE: 1,
    Disposition.NOT_ACCEPTABLE: 2,
    Disposition.IMMEDIATE_REPAIR: 3,
    Disposition.OUT_OF_SCOPE: 3,   # escalation treated as high-attention
}


def governing_result(results: dict[str, AssessmentResult]) -> AssessmentResult:
    def key(r: AssessmentResult):
        return (_SEVERITY[r.disposition], r.erf if r.erf is not None else 0.0)
    return max(results.values(), key=key)


_ACTION_BY_DISPOSITION = {
    Disposition.ACCEPTABLE_MONITOR: (
        "No repair required. Record defect, include in corrosion-growth "
        "monitoring, and confirm at next ILI run.",
        "ASME B31G-2012 (d/t < 0.10)"),
    Disposition.ACCEPTABLE: (
        "Defect acceptable at MAOP (ERF < 1.0). No immediate repair required; "
        "record, apply corrosion growth rate to schedule re-inspection, and "
        "verify dimensions in field if ILI-reported (tool tolerance).",
        "ASME B31G-2012 Level 1"),
    Disposition.NOT_ACCEPTABLE: (
        "Defect NOT acceptable at MAOP (ERF >= 1.0). Either (a) repair using a "
        "permitted method below, or (b) as interim measure reduce operating "
        "pressure to <= Psafe pending repair, or (c) escalate to Level 2 "
        "(RSTRENG effective area) / API 579-1 Part 5 with field-verified "
        "river-bottom profile before final decision.",
        "ASME B31G-2012; ASME B31.4 para 451.6"),
    Disposition.IMMEDIATE_REPAIR: (
        "Depth exceeds 80% of wall thickness: not acceptable at any pressure. "
        "Repair with pressure-containing method (Type B sleeve) or cut-out "
        "and replace. Consider immediate pressure reduction and exposure "
        "control until repaired.",
        "ASME B31G-2012 (d/t <= 0.80 limit); ASME B31.4 para 451.6"),
    Disposition.OUT_OF_SCOPE: (
        "Outside B31G Level-1 scope. Do not disposition with Level 1: obtain "
        "field measurements / river-bottom profile and assess per B31G "
        "Level 2 (effective area) or API 579-1 FFS Part 4/5; crack-like "
        "indications go to API 579-1 Part 9.",
        "ASME B31G-2012 para 1.2; API 579-1/ASME FFS-1"),
}


def recommend(defect: DefectRecord, pipe: PipeSpec) -> dict[str, Any]:
    results = assess_both(defect, pipe)
    gov = governing_result(results)
    action_text, action_ref = _ACTION_BY_DISPOSITION[gov.disposition]

    repair_opts = select_repair_options(defect, gov)
    sop = build_sop_checklist(defect)

    card: dict[str, Any] = {
        "rules_version": RULES_VERSION,
        "defect": defect.model_dump(),
        "pipe": pipe.model_dump(),
        "assessments": {k: asdict(v) for k, v in results.items()},
        "governing_method": gov.method.value,
        "disposition": gov.disposition.value,
        "erf": gov.erf,
        "safe_pressure_mpa": gov.safe_pressure_mpa,
        "required_action": {"action": action_text, "reference": action_ref},
        "permitted_repair_options": [asdict(o) for o in repair_opts],
        "field_verification_and_sop": [asdict(s) for s in sop],
        "caveats": [
            "ILI-reported dimensions include tool sizing tolerance; final "
            "disposition should use field-verified (UT) dimensions "
            "(defect.field_verified flag).",
            "This module implements B31G Level 1 only. Interacting defects, "
            "dents with metal loss, weld-zone anomalies and cracks must be "
            "escalated as flagged.",
            "SOP items marked [PLACEHOLDER - CONFIRM ...] are drafts pending "
            "site-engineer confirmation.",
        ],
    }
    return card


# --------------------------------------------------------------------------
# ILI CSV importer (both-source support)
# --------------------------------------------------------------------------

# Map common ILI vendor headers -> our schema. Extend as needed for the
# actual RKPL vendor listing (share one sample row and I will pin these).
_HEADER_ALIASES = {
    "defect_id": ["defect_id", "feature id", "feature_id", "anomaly id", "id"],
    "log_distance_m": ["log_distance_m", "log dist. [m]", "log distance [m]",
                       "odometer [m]", "abs. distance [m]"],
    "depth_pct": ["depth_pct", "depth [%]", "depth %", "peak depth [%]"],
    "length_mm": ["length_mm", "length [mm]", "axial length [mm]"],
    "width_mm": ["width_mm", "width [mm]", "circ. extent [mm]"],
    "orientation_oclock": ["orientation_oclock", "o'clock", "oclock",
                           "orientation"],
    "defect_type": ["defect_type", "identification", "feature type",
                    "anomaly type", "int/ext", "internal/external"],
}

_TYPE_MAP = {
    "external": DefectType.EXTERNAL_METAL_LOSS,
    "ext": DefectType.EXTERNAL_METAL_LOSS,
    "internal": DefectType.INTERNAL_METAL_LOSS,
    "int": DefectType.INTERNAL_METAL_LOSS,
    "pitting": DefectType.PITTING,
    "external_metal_loss": DefectType.EXTERNAL_METAL_LOSS,
    "internal_metal_loss": DefectType.INTERNAL_METAL_LOSS,
    "axial_grooving": DefectType.AXIAL_GROOVING,
    "circumferential_grooving": DefectType.CIRCUMFERENTIAL_GROOVING,
}


def _norm(h: str) -> str:
    return h.strip().lower()


def parse_ili_csv(text: str) -> tuple[list[DefectRecord], list[str]]:
    """Parse an ILI vendor CSV. Returns (records, row_errors).

    Unmappable rows are reported, never silently guessed.
    """
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return [], ["Empty file or no header row."]

    col_for: dict[str, str] = {}
    lowered = {_norm(h): h for h in reader.fieldnames}
    for target, aliases in _HEADER_ALIASES.items():
        for a in aliases:
            if a in lowered:
                col_for[target] = lowered[a]
                break

    missing = [t for t in ("depth_pct", "length_mm") if t not in col_for]
    if missing:
        return [], [f"Required column(s) not found: {missing}. "
                    f"Headers seen: {reader.fieldnames}. "
                    "Update _HEADER_ALIASES for this vendor format."]

    records, errors = [], []
    for i, row in enumerate(reader, start=2):
        try:
            raw_type = _norm(row.get(col_for.get("defect_type", ""), "") or "")
            dtype = None
            for k, v in _TYPE_MAP.items():
                if k in raw_type:
                    dtype = v
                    break
            if dtype is None:
                errors.append(f"Row {i}: unrecognised defect type "
                              f"'{raw_type}' — row skipped (no guessing).")
                continue
            rec = DefectRecord(
                defect_id=str(row.get(col_for.get("defect_id", ""), f"ROW{i}")
                              or f"ROW{i}"),
                defect_type=dtype,
                log_distance_m=float(row[col_for["log_distance_m"]])
                if "log_distance_m" in col_for and row[col_for["log_distance_m"]]
                else None,
                depth_pct=float(row[col_for["depth_pct"]]),
                length_mm=float(row[col_for["length_mm"]]),
                width_mm=float(row[col_for["width_mm"]])
                if "width_mm" in col_for and row[col_for["width_mm"]] else None,
                orientation_oclock=row.get(col_for.get("orientation_oclock", ""))
                or None,
                source="ili",
            )
            records.append(rec)
        except (ValueError, KeyError) as e:
            errors.append(f"Row {i}: {e} — row skipped.")
    return records, errors
