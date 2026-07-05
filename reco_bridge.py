"""reco_bridge.py — connects rkpl_health ILI data to integrity_reco.

Maps a row of the ILI anomaly table (ILI_anomalies_RKPL_SEC2_REAL.csv schema,
or a session-uploaded ILI file normalized by app.normalize_columns) into a
DefectRecord, using the PER-FEATURE wall thickness from the pigging listing.

Also compares the engine's ERF/Psafe with the vendor-reported values
(erf_b31g / psafe_kg_cm2 columns) so every recommendation card shows an
independent validation against LIN SCAN's own B31G assessment.
"""

from __future__ import annotations

import pandas as pd

from integrity_reco.models import DefectRecord, DefectType, PipeSpec
from integrity_reco.recommend import recommend

KGCM2_TO_MPA = 0.0980665


def enrich_ili_with_erf(df: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, int]:
    """If an uploaded ILI table has no vendor erf_b31g/psafe columns, compute
    them with the app's validated Original-B31G engine (the method LIN SCAN
    used) so the health-score engine and repair tab work identically for any
    vendor file. Rows lacking depth/length/wt are left as NaN, never guessed.

    Returns (df, n_computed).
    """
    from integrity_reco.b31g import assess_original
    from integrity_reco.models import DefectRecord, DefectType

    df = df.copy()
    if "erf_b31g" not in df.columns:
        df["erf_b31g"] = pd.NA
    if "psafe_kg_cm2" not in df.columns:
        df["psafe_kg_cm2"] = pd.NA

    n = 0
    for i, r in df.iterrows():
        if pd.notna(r.get("erf_b31g")):
            continue  # vendor value present; never overwrite
        depth, length, wt = r.get("depth_pct_wt"), r.get("axial_length_mm"), r.get("wt_mm")
        if pd.isna(depth) or pd.isna(length) or pd.isna(wt):
            continue  # insufficient data; leave NaN (depth-only scoring applies)
        try:
            res = assess_original(
                DefectRecord(defect_id=f"enrich-{i}",
                             defect_type=DefectType.EXTERNAL_METAL_LOSS,
                             depth_pct=float(depth), length_mm=float(length)),
                pipe_from_cfg(cfg, float(wt)))
            if res.safe_pressure_mpa:
                psafe_kg = res.safe_pressure_mpa / KGCM2_TO_MPA
                df.at[i, "psafe_kg_cm2"] = round(psafe_kg, 1)
                df.at[i, "erf_b31g"] = round(cfg["pipe"]["maop_kg_cm2"] / psafe_kg, 3)
                n += 1
            elif res.disposition.value == "immediate_repair":
                # d/t > 80%: no Psafe exists; force worst ILI score via high ERF
                df.at[i, "erf_b31g"] = 9.99
                n += 1
        except Exception:
            continue  # invalid row values; leave NaN rather than crash
    return df, n


def pipe_from_cfg(cfg: dict, wt_mm: float) -> PipeSpec:
    p = cfg["pipe"]
    return PipeSpec(
        outside_diameter_mm=p["outside_diameter_mm"],
        wall_thickness_mm=wt_mm,                      # per-feature WT from ILI
        smys_mpa=p["smys_mpa"],
        maop_mpa=p["maop_kg_cm2"] * KGCM2_TO_MPA,
        design_factor=p.get("design_factor", 0.72),
    )


def row_to_defect(row: pd.Series, idx: int) -> DefectRecord:
    loc = str(row.get("location_int_ext", "External")).lower()
    dtype = (DefectType.INTERNAL_METAL_LOSS if loc.startswith("int")
             else DefectType.EXTERNAL_METAL_LOSS)
    return DefectRecord(
        defect_id=f"ILI-{idx:03d}@{row['chainage_km']:.3f}km",
        defect_type=dtype,
        log_distance_m=float(row["abs_distance_m"]) if "abs_distance_m" in row and pd.notna(row.get("abs_distance_m")) else None,
        depth_pct=float(row["depth_pct_wt"]),
        length_mm=float(row["axial_length_mm"]),
        width_mm=float(row["width_mm"]) if pd.notna(row.get("width_mm")) else None,
        orientation_oclock=str(row.get("orientation_oclock") or "") or None,
        source="ili",
    )


def recommend_for_row(row: pd.Series, idx: int, cfg: dict) -> dict:
    pipe = pipe_from_cfg(cfg, float(row["wt_mm"]))
    card = recommend(row_to_defect(row, idx), pipe)
    # vendor cross-validation block
    if pd.notna(row.get("erf_b31g")) and pd.notna(row.get("psafe_kg_cm2")):
        eng = card["assessments"]["original"]  # LIN SCAN calibrated to Original B31G
        card["vendor_comparison"] = {
            "vendor_erf": float(row["erf_b31g"]),
            "vendor_psafe_kg_cm2": float(row["psafe_kg_cm2"]),
            "engine_erf_original": round(eng["erf"], 3) if eng["erf"] else None,
            "engine_psafe_kg_cm2_original": (
                round(eng["safe_pressure_mpa"] / KGCM2_TO_MPA, 1)
                if eng["safe_pressure_mpa"] else None),
        }
        e, v = card["vendor_comparison"]["engine_erf_original"], row["erf_b31g"]
        if e is not None:
            card["vendor_comparison"]["match_within_2pct"] = abs(e - v) / v < 0.02
    return card
