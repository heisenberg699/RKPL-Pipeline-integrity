# RKPL Pipeline Health Scoring — Demo Data Package

## Contents
| File | Source | Notes |
|---|---|---|
| DCVG_RKPL_SEC2_REAL.csv | REAL — AMC report AMC/HPCL/RKPL/DCVG/SEC-2 annexure | 27 spans, 5 moderate defects |
| ILI_anomalies_RKPL_SEC2_REAL.csv | REAL — LIN SCAN pipetally Rev 0 | 10 metal-loss anomalies, chainage already datum-converted (+141.935 km) |
| CIPL_ONOFF_RKPL_SEC2_SYNTHETIC.csv | Synthetic | Under-protection injected near real DCVG defect zones (physically consistent) |
| DC_INTERFERENCE_RKPL_SEC2_SYNTHETIC.csv | Semi-synthetic | Real crossing chainages from AMC DC-Interference report; swings synthetic |
| CAT_RKPL_SEC2_SYNTHETIC.csv | Derived | Attenuation computed from real DCVG S1/S2 signal decay |
| SOIL_RESISTIVITY_RKPL_SEC2_SYNTHETIC.csv | Synthetic | Yamuna alluvial range; corrosive pocket at ~148 km |
| SEGMENT_HEALTH_SCORES.csv | OUTPUT | 231 × 100 m segments, pre-scored |
| scoring_engine.py | Code | Reusable module: load CSVs → score → weighted health |
| scoring_config.json | Config | All thresholds/weights editable, no code change needed |

## Key facts for your presentation
- Datum reconciliation: ILI abs-distance + 141.935 km = route chainage (verified: receiver 23,014 m → 164.949 ≈ TLP 164.950).
- Correlation showcase: ILI external metal loss at 153.652 km sits ~260 m from DCVG coating defect 153.388 km; ILI internal cluster at 163.51 km sits inside the DCVG defect span 163.050–164.950 (defect at 164.942).
- Result on real data: Pipeline KPI 95.4/100, 6 Watch segments, 0 Critical — matches AMC's conclusion (moderate defects only, 4 of 5 already repaired).

## Demo moment (live upload)
Upload `DEMO_UPLOAD_bad_cipl.csv` during the presentation: an under-protected OFF reading (-0.72 V) at Ch 153.40 compounds with the existing DCVG defect there → segment 153.3–153.4 drops into Critical in real time.
