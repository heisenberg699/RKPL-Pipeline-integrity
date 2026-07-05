# Quick start (Windows/Linux)
pip install -r requirements.txt
streamlit run app.py

# Demo script (4 minutes)
1. OVERVIEW tab — KPI 96.1, strip chart shows amber zones at your 5 real DCVG defects + red-adjacent ILI cluster at 163.5 km.
2. DRILL-DOWN — pick Ch 163.5: shows the 7 real internal-corrosion ILI anomalies, transparent weight math, GPS map pin.
3. UPLOAD — drop DEMO_UPLOAD_bad_cipl.csv → confirm → Overview shows "What changed": Ch 153.3 drops 79.6 → 56.1 (-23.5) because the bad CP reading compounds with the real DCVG coating defect there.
4. SETTINGS — drag ILI weight slider → instant full-pipeline rescore.

# Talking points
- Datum reconciliation: ILI abs-distance + 141.935 km = route chainage (verified against TLP 164.950).
- Conservative scoring: worst reading per 100 m segment; weights renormalize when a survey is absent.
- All thresholds config-driven (scoring_config.json) — NACE SP0169 / RP0502 / ASME B31G basis.
