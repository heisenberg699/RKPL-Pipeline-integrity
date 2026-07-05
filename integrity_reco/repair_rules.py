"""
integrity_reco.repair_rules
===========================
Deterministic repair-option mapping and site SOP registry.

Two layers, kept visibly separate in every output:

  1. STANDARDS layer  — repair methods permitted for the defect situation,
     per ASME PCC-2 (Repair of Pressure Equipment and Piping), ASME B31.4
     Ch. VII (para 451.6, pipeline repairs), API 1104 (repair welding),
     and OISD guidance. This table is static and versioned; the app only
     SELECTS rows from it, never generates text.

  2. SITE SOP layer   — RKPL-specific field verification / rectification
     checklists. HARD-CODED here by design (per user decision); edit this
     file to change them. Items marked [PLACEHOLDER - CONFIRM] must be
     reviewed by the site engineer before the module is treated as final.

IMPORTANT ENGINEERING NOTE (encoded in the rules below):
  - Non-metallic composite repair systems (PCC-2 Article 4.1/4.2) are for
    NON-LEAKING defects only.
  - A leaking defect requires a welded pressure-containing repair:
    Type B full-encirclement sleeve (PCC-2 Article 2.6 / B31.4) or cut-out
    and replacement. Type A sleeves and composites are NOT permitted on leaks.
  - Weld deposition (buildup) repair is limited to defects meeting
    depth/extent limits and requires a qualified procedure (PCC-2 Art. 2.9,
    API 1104).
  - Grinding is a removal method for shallow defects only, subject to
    remaining-wall verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .b31g import AssessmentResult, Disposition
from .models import DefectRecord, LeakStatus

RULES_VERSION = "0.1.0-draft"  # bump when the tables below change


# --------------------------------------------------------------------------
# Layer 1: standards-based repair options
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RepairOption:
    method: str
    permitted_when: str
    reference: str
    constraints: str


REPAIR_CATALOGUE: list[RepairOption] = [
    RepairOption(
        method="Grind-out (defect removal) + UT verification",
        permitted_when="non_leaking_shallow",
        reference="ASME PCC-2 Article 3.3 (flaw excavation); ASME B31.4 para 451.6",
        constraints=("Only where remaining wall after grinding still satisfies "
                     "B31G at MAOP; smooth contour; MPI/DPI after grinding; "
                     "UT wall-thickness verification of ground area."),
    ),
    RepairOption(
        method="Non-metallic composite wrap (qualified system)",
        permitted_when="non_leaking",
        reference="ASME PCC-2 Article 4.1 (non-leaking components); ISO 24817",
        constraints=("NOT permitted on leaking defects. Requires qualified "
                     "system + design calculation per PCC-2 Art. 4.1 appendices; "
                     "surface prep per system datasheet; not for defects that "
                     "will breach wall within repair design life (corrosion "
                     "growth allowance to be included)."),
    ),
    RepairOption(
        method="Type A full-encirclement steel sleeve (reinforcing, ends not welded to pipe)",
        permitted_when="non_leaking",
        reference="ASME PCC-2 Article 2.6; ASME B31.4 para 451.6.2",
        constraints=("NOT for leaking defects; reinforces but does not contain "
                     "pressure. Hardenability/carbon-equivalent check for any "
                     "welding near the carrier pipe."),
    ),
    RepairOption(
        method="Type B full-encirclement steel sleeve (pressure-containing, ends fillet-welded)",
        permitted_when="any",
        reference="ASME PCC-2 Article 2.6; ASME B31.4 para 451.6.2; API 1104 (in-service welding per Appendix B)",
        constraints=("Permitted for leaking and non-leaking defects. In-service "
                     "welding controls: qualified low-hydrogen procedure, "
                     "burn-through risk assessment vs. remaining wall and flow "
                     "conditions, NDT of sleeve welds."),
    ),
    RepairOption(
        method="Weld deposition (deposited weld metal buildup)",
        permitted_when="non_leaking_limited",
        reference="ASME PCC-2 Article 2.9; API 1104",
        constraints=("Limited application; qualified in-service welding "
                     "procedure; remaining wall must be adequate against "
                     "burn-through; NDT (UT + MPI) of deposit."),
    ),
    RepairOption(
        method="Cut-out and replacement with pre-tested pipe (pup piece)",
        permitted_when="any",
        reference="ASME B31.4 para 451.6.2; API 1104 (girth welds); OISD-STD-141",
        constraints=("Definitive repair; requires line shutdown/isolation and "
                     "de-oiling or stopple/bypass; replacement pipe of same or "
                     "higher grade and wall, hydrotested or pre-tested; girth "
                     "welds 100% RT/UT per API 1104."),
    ),
    RepairOption(
        method="Temporary pressure reduction (derate to Psafe)",
        permitted_when="interim_only",
        reference="ASME B31G-2012 (Psafe); ASME B31.4; PNGRB IMS Regulations 2019",
        constraints=("Interim mitigation ONLY, pending permanent repair. "
                     "Operate at or below calculated Psafe; document in "
                     "MOC/deviation; define repair deadline."),
    ),
]


def select_repair_options(defect: DefectRecord,
                          governing: AssessmentResult) -> list[RepairOption]:
    """Pure table lookup: which catalogue rows apply to this situation."""
    leaking = defect.leak_status == LeakStatus.LEAKING
    dt = defect.depth_fraction
    opts: list[RepairOption] = []

    for opt in REPAIR_CATALOGUE:
        if leaking:
            if opt.permitted_when == "any":
                opts.append(opt)
            continue
        # non-leaking:
        if opt.permitted_when in ("any", "non_leaking"):
            opts.append(opt)
        elif opt.permitted_when == "non_leaking_shallow" and dt <= 0.40:
            opts.append(opt)
        elif opt.permitted_when == "non_leaking_limited" and dt <= 0.80:
            opts.append(opt)
        elif (opt.permitted_when == "interim_only"
              and governing.disposition == Disposition.NOT_ACCEPTABLE
              and governing.safe_pressure_mpa is not None):
            opts.append(opt)
    return opts


# --------------------------------------------------------------------------
# Layer 2: hard-coded site SOP registry (RKPL) — edit via Claude on request
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SOPItem:
    step: str
    basis: str          # "Standard requirement" or "Site SOP"
    reference: str = ""


SOP_REGISTRY: dict[str, list[SOPItem]] = {
    # applies to every metal-loss defect before the assessment is trusted
    "verification_common": [
        SOPItem("Locate defect in field from ILI chainage using above-ground "
                "markers / weld count; excavate per approved excavation "
                "checklist and permit-to-work.",
                "Site SOP", "[RKPL/Civil/01]"),
        SOPItem("Direct measurement of defect: UT compression-probe grid "
                "(recommend 100 mm x 100 mm or finer over the anomaly + 200 mm "
                "beyond), pit gauge for depth, record max depth and axial length.",
                "Standard requirement",
                "ASME B31G-2012 (measured dimensions govern re-assessment)"),
        SOPItem("Re-run B31G with FIELD-VERIFIED depth/length; ILI-reported "
                "dimensions carry tool tolerance (see API 1163 vendor "
                "performance spec).",
                "Standard requirement", "API 1163"),
        SOPItem("Record coating type and condition, holiday location, and "
                "photograph before and after surface preparation.",
                "Site SOP", "[RKPL/Coating/01]"),
        SOPItem("Measure pipe-to-soil CP potential (ON and instant-OFF) at the "
                "excavation; verify against -850 mV (CSE, polarized) criterion; "
                "investigate CP shielding/coating disbondment if external "
                "corrosion is confirmed.",
                "Standard requirement", "NACE/AMPP SP0169; NACE TM0497"),
        SOPItem("Soil sample and resistivity at defect depth for external ML "
                "root-cause record.",
                "Site SOP", "[RKPL/CP/01]"),
        SOPItem("MPI/DPI of the metal-loss area to rule out crack-like "
                "features (cracks are outside B31G scope; escalate to "
                "API 579-1 Part 9 if found).",
                "Standard requirement", "ASME B31G-2012 para 1.2"),
    ],
    "internal_metal_loss_extra": [
        SOPItem("Review product corrosivity: BS&W/water content trend, "
                "corrosion coupon / ER probe data for the section; check low "
                "points and over-bend locations for water hold-up.",
                "Standard requirement", "NACE SP0208 (liquid petroleum ICDA)"),
        SOPItem("Verify pigging frequency and last cleaning-pig debris record "
                "for the section.",
                "Site SOP", "[RKPL/Mech/01]"),
    ],
    "rectification_common": [
        SOPItem("Execute repair under permit-to-work with job-specific JSA; "
                "in-service welding (if any) per qualified procedure with "
                "burn-through assessment.",
                "Standard requirement", "ASME PCC-2; API 1104 App. B"),
        SOPItem("Post-repair NDT: sleeve fillet welds MPI + UT as applicable; "
                "composite repair cure verification per system datasheet.",
                "Standard requirement", "ASME PCC-2 Articles 2.6 / 4.1"),
        SOPItem("Restore coating (compatible field joint system), backfill "
                "with padding, restore CP continuity, post-backfill CP "
                "potential check.",
                "Standard requirement", "NACE/AMPP SP0169"),
        SOPItem("Update pipeline integrity database (rkpl_health) with "
                "field-verified dimensions, repair type, and date; feed into "
                "corrosion growth-rate model for re-inspection interval.",
                "Site SOP", "rkpl_health data-entry procedure"),
        SOPItem("Regulatory records: retain assessment + repair documentation "
                "per PNGRB Integrity Management System regulations; report "
                "as applicable.",
                "Standard requirement",
                "PNGRB (IMS for PNG/petroleum pipelines) Regulations"),
    ],
}


def build_sop_checklist(defect: DefectRecord) -> list[SOPItem]:
    items = list(SOP_REGISTRY["verification_common"])
    if defect.defect_type.value.startswith("internal") :
        items += SOP_REGISTRY["internal_metal_loss_extra"]
    items += SOP_REGISTRY["rectification_common"]
    return items
