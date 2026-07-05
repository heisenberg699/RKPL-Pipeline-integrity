"""
integrity_reco.b31g
===================
Deterministic implementation of ASME B31G-2012 (R2017) Level-1 methods:

  - Level 1, Original B31G   (Clause 1.7 / Appendix; parabolic area, flow
    stress = 1.1 * SMYS, Folias M = sqrt(1 + 0.8 z), z <= 20 limit)
  - Level 1, Modified B31G   ("0.85 dL" method; flow stress = SMYS + 69 MPa,
    two-branch Folias factor)

No probabilistic or AI content: every result is a pure function of the
inputs, and every result object carries the formula branch and intermediate
values used, so it can be hand-checked against the standard.

Symbols follow the standard:
  D  = outside diameter          t = nominal wall thickness
  d  = max defect depth          L = axial defect length
  z  = L^2 / (D t)               M = Folias (bulging) factor
  Sf = predicted failure stress  Pf = predicted failure pressure = 2 Sf t / D
  Psafe = F * Pf   (F = design factor, 0.72 for B31.4 liquid lines)
  ERF  = MAOP / Psafe   (Estimated Repair Factor; ERF > 1.0 => not acceptable
         at current MAOP)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .models import DefectRecord, PipeSpec

MPA_PER_KSI = 6.894757  # exact enough for 10 ksi = 68.95 MPa


class Method(str, Enum):
    B31G_ORIGINAL = "ASME B31G-2012 Level 1 (Original)"
    B31G_MODIFIED = "ASME B31G-2012 Level 1 (Modified, 0.85dL)"


class Disposition(str, Enum):
    ACCEPTABLE_MONITOR = "acceptable_monitor"
    ACCEPTABLE = "acceptable"
    NOT_ACCEPTABLE = "not_acceptable"          # repair, replace, or derate
    IMMEDIATE_REPAIR = "immediate_repair"      # depth > 80% wt
    OUT_OF_SCOPE = "out_of_level1_scope"       # escalate to Level 2/3 or API 579


@dataclass
class AssessmentResult:
    method: Method
    disposition: Disposition
    d_over_t: float
    z_param: Optional[float] = None
    folias_m: Optional[float] = None
    flow_stress_mpa: Optional[float] = None
    failure_stress_mpa: Optional[float] = None
    failure_pressure_mpa: Optional[float] = None
    safe_pressure_mpa: Optional[float] = None
    erf: Optional[float] = None
    formula_branch: str = ""
    notes: list[str] = field(default_factory=list)
    standard_reference: str = ""


def _scope_check(defect: DefectRecord, pipe: PipeSpec) -> Optional[AssessmentResult]:
    """Level-1 applicability gates common to both methods.

    B31G Level 1 applies to blunt metal-loss defects in ductile line pipe,
    away from interaction with other defects. Cracks, dents, weld-zone
    anomalies and interacting clusters are outside Level-1 scope.
    """
    dt = defect.depth_fraction
    notes: list[str] = []

    if defect.interacting:
        return AssessmentResult(
            method=Method.B31G_ORIGINAL, disposition=Disposition.OUT_OF_SCOPE,
            d_over_t=dt,
            formula_branch="scope_gate",
            notes=["Interacting defect cluster: outside B31G Level-1 scope. "
                   "Assess per B31G Level 2 (effective area / RSTRENG) or "
                   "API 579-1 Part 5, or treat as single defect of combined "
                   "length as a conservative screen."],
            standard_reference="ASME B31G-2012, para. 1.2 (applicability)",
        )
    if defect.near_weld:
        notes.append(
            "Defect within 25 mm of weld: confirm weld type and ductility; "
            "seam-weld anomalies are outside Level-1 scope "
            "(ASME B31G-2012 para 1.2)."
        )

    if dt > 0.80:
        return AssessmentResult(
            method=Method.B31G_ORIGINAL,
            disposition=Disposition.IMMEDIATE_REPAIR,
            d_over_t=dt,
            formula_branch="depth_gate",
            notes=notes + ["Depth > 80% of wall thickness: defect is not "
                           "acceptable at any pressure per B31G; repair or "
                           "replace."],
            standard_reference="ASME B31G-2012, acceptance limit d/t <= 0.80",
        )
    return None  # in scope; proceed to calculation


def assess_original(defect: DefectRecord, pipe: PipeSpec) -> AssessmentResult:
    """Original B31G, Level 1."""
    gate = _scope_check(defect, pipe)
    if gate is not None:
        gate.method = Method.B31G_ORIGINAL
        return gate

    D, t = pipe.outside_diameter_mm, pipe.wall_thickness_mm
    L = defect.length_mm
    dt = defect.depth_fraction

    if dt < 0.10:
        return AssessmentResult(
            method=Method.B31G_ORIGINAL,
            disposition=Disposition.ACCEPTABLE_MONITOR,
            d_over_t=dt, formula_branch="shallow_gate",
            notes=["Depth < 10% wall thickness: acceptable without pressure "
                   "calculation; record and monitor for growth."],
            standard_reference="ASME B31G-2012, d/t < 0.10 acceptance",
        )

    z = L * L / (D * t)
    s_flow = 1.1 * pipe.smys_mpa

    if z <= 20.0:
        m = math.sqrt(1.0 + 0.8 * z)
        sf = s_flow * (1.0 - (2.0 / 3.0) * dt) / (1.0 - (2.0 / 3.0) * dt / m)
        branch = "z<=20: parabolic area, M=sqrt(1+0.8z)"
    else:
        m = None
        sf = s_flow * (1.0 - dt)  # long defect: rectangular area assumption
        branch = "z>20: long-defect (rectangular) limit, Sf = Sflow*(1-d/t)"

    pf = 2.0 * sf * t / D
    psafe = pipe.design_factor * pf
    erf = pipe.maop_mpa / psafe if psafe > 0 else float("inf")

    disposition = Disposition.ACCEPTABLE if erf < 1.0 else Disposition.NOT_ACCEPTABLE
    return AssessmentResult(
        method=Method.B31G_ORIGINAL, disposition=disposition,
        d_over_t=dt, z_param=z, folias_m=m, flow_stress_mpa=s_flow,
        failure_stress_mpa=sf, failure_pressure_mpa=pf,
        safe_pressure_mpa=psafe, erf=erf, formula_branch=branch,
        standard_reference="ASME B31G-2012 (R2017), Level 1, Original method",
        notes=(["ERF >= 1.0: reduce operating pressure to Psafe, or repair, "
                "or re-assess with Modified B31G / Level 2."] if erf >= 1.0 else []),
    )


def assess_modified(defect: DefectRecord, pipe: PipeSpec) -> AssessmentResult:
    """Modified B31G (0.85 dL), Level 1."""
    gate = _scope_check(defect, pipe)
    if gate is not None:
        gate.method = Method.B31G_MODIFIED
        return gate

    D, t = pipe.outside_diameter_mm, pipe.wall_thickness_mm
    L = defect.length_mm
    dt = defect.depth_fraction

    if dt < 0.10:
        return AssessmentResult(
            method=Method.B31G_MODIFIED,
            disposition=Disposition.ACCEPTABLE_MONITOR,
            d_over_t=dt, formula_branch="shallow_gate",
            notes=["Depth < 10% wall thickness: acceptable; record and monitor."],
            standard_reference="ASME B31G-2012, d/t < 0.10 acceptance",
        )

    z = L * L / (D * t)
    s_flow = pipe.smys_mpa + 10.0 * MPA_PER_KSI  # SMYS + 68.95 MPa (10 ksi)

    if z <= 50.0:
        m = math.sqrt(1.0 + 0.6275 * z - 0.003375 * z * z)
        branch = "z<=50: M=sqrt(1+0.6275z-0.003375z^2)"
    else:
        m = 0.032 * z + 3.3
        branch = "z>50: M=0.032z+3.3"

    sf = s_flow * (1.0 - 0.85 * dt) / (1.0 - 0.85 * dt / m)
    pf = 2.0 * sf * t / D
    psafe = pipe.design_factor * pf
    erf = pipe.maop_mpa / psafe if psafe > 0 else float("inf")

    disposition = Disposition.ACCEPTABLE if erf < 1.0 else Disposition.NOT_ACCEPTABLE
    return AssessmentResult(
        method=Method.B31G_MODIFIED, disposition=disposition,
        d_over_t=dt, z_param=z, folias_m=m, flow_stress_mpa=s_flow,
        failure_stress_mpa=sf, failure_pressure_mpa=pf,
        safe_pressure_mpa=psafe, erf=erf, formula_branch=branch,
        standard_reference="ASME B31G-2012 (R2017), Level 1, Modified (0.85dL)",
        notes=(["ERF >= 1.0: reduce operating pressure to Psafe, or repair, "
                "or escalate to Level 2 (RSTRENG) / API 579-1 Part 5."]
               if erf >= 1.0 else []),
    )


def assess_both(defect: DefectRecord, pipe: PipeSpec) -> dict[str, AssessmentResult]:
    return {
        "original": assess_original(defect, pipe),
        "modified": assess_modified(defect, pipe),
    }
