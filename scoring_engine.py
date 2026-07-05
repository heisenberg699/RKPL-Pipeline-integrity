"""Pipeline Integrity Health Scoring Engine — RKPL Hackathon.
Config-driven: all thresholds/weights in scoring_config.json.
Usage:  python scoring_engine.py  (reads CSVs in same dir, writes SEGMENT_HEALTH_SCORES.csv)
Or import: from scoring_engine import ScoringEngine
"""
import json, os
import numpy as np, pandas as pd

class ScoringEngine:
    def __init__(self, config_path="scoring_config.json"):
        self.cfg = json.load(open(config_path))
        self.W = self.cfg["weights"]
        p = self.cfg["pipeline"]
        self.seg_len = p["segment_length_km"]
        self.start, self.end = p["start_km"], p["end_km"]
        self.offset = p["ili_datum_offset_km"]
        self.scores = {k: {} for k in self.W}

    # ---------- helpers ----------
    def _interp(self, x, pts):
        xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
        return float(np.clip(np.interp(x, xs, ys), 0, 100))

    def _seg(self, ch):
        return round(np.floor(ch / self.seg_len) * self.seg_len, 1)

    def _put(self, survey, seg, val):
        self.scores[survey][seg] = min(self.scores[survey].get(seg, 100.0), val)

    def _segments(self):
        return np.round(np.arange(self.start - self.start % self.seg_len,
                                  self.end, self.seg_len), 1)

    # ---------- per-survey scorers ----------
    def score_dcvg(self, ir): return self._interp(ir, self.cfg["thresholds"]["dcvg_pct_ir"])

    def score_off(self, v):
        lo, hi = self.cfg["thresholds"]["cipl_off_protected_window_v"]  # [-1.20,-0.85]
        if lo <= v <= hi: return 100.0
        if lo - 0.15 <= v < lo: return 85.0          # slight over-protection
        if v < lo - 0.15: return 60.0                # over-protection / disbondment risk
        if hi < v <= hi + 0.05: return self._interp(-v, [(0.80, 45), (0.85, 70)])
        if hi + 0.05 < v <= hi + 0.15: return self._interp(-v, [(0.70, 20), (0.80, 45)])
        return max(0.0, 20 * (-v) / 0.70)

    def score_ili(self, depth, erf):
        sd = self._interp(depth, self.cfg["thresholds"]["ili_depth_pct"])
        se = 100.0 if erf < 0.90 else self._interp(erf, self.cfg["thresholds"]["ili_erf"])
        return min(sd, se)

    def score_dci(self, swing): return self._interp(swing, self.cfg["thresholds"]["dci_swing_mv"])

    def score_cat(self, att):
        a = abs(att)
        t = self.cfg["thresholds"]["cat_attenuation"]
        return 100.0 if a <= t[0][0] else self._interp(a, t)

    def score_soil(self, r):
        for lo, s in self.cfg["thresholds"]["soil_resistivity_ohm_cm"]:
            if r >= lo: return float(s)
        return 25.0

    # ---------- ingestion (column names fuzzy-matched upstream in the app) ----------
    def ingest_dcvg(self, df):
        for _, r in df.iterrows():
            for s in self._segments():
                if r["chainage_from_km"] <= s < r["chainage_to_km"]:
                    self.scores["DCVG"].setdefault(s, 100.0)
            if pd.notna(r.get("pct_ir")):
                self._put("DCVG", self._seg(r["defect_chainage_km"]), self.score_dcvg(r["pct_ir"]))

    def ingest_ili(self, df, chainage_is_abs_distance=False):
        for s in self._segments():
            if self.start <= s <= self.end: self.scores["ILI"].setdefault(s, 100.0)
        for _, r in df.iterrows():
            if chainage_is_abs_distance:
                if pd.isna(r.get("abs_distance_m")): continue
                ch = r["abs_distance_m"] / 1000 + self.offset
            else:
                if pd.isna(r.get("chainage_km")): continue
                ch = r["chainage_km"]
            depth = r.get("depth_pct_wt")
            if pd.isna(depth): continue                      # cannot score without depth
            erf = r.get("erf_b31g")
            erf = 0.0 if pd.isna(erf) else float(erf)        # no ERF -> depth-only scoring
            self._put("ILI", self._seg(ch), self.score_ili(float(depth), erf))

    def ingest_cipl(self, df):
        for _, r in df.iterrows():
            self._put("CIPL", self._seg(r["chainage_km"]), self.score_off(r["off_potential_v_cse"]))

    def ingest_dci(self, df):
        for _, r in df.iterrows():
            self._put("DCI", self._seg(r["chainage_km"]), self.score_dci(r["positive_swing_mv"]))

    def ingest_cat(self, df):
        for _, r in df.iterrows():
            for s in self._segments():
                if r["chainage_from"] <= s < r["chainage_to"]:
                    self._put("CAT", s, self.score_cat(r["attenuation_mb_per_m"]))

    def ingest_soil(self, df):
        for _, r in df.iterrows():
            self._put("SOIL", self._seg(r["chainage_km"]), self.score_soil(r["resistivity_ohm_cm"]))

    # ---------- weighted health ----------
    def compute(self):
        lab = self.cfg["severity_labels"]; comp = self.cfg["compounding"]
        rows = []
        for s in self._segments():
            avail = {k: v[s] for k, v in self.scores.items() if s in v}
            if not avail: continue
            tw = sum(self.W[k] for k in avail)
            h = sum(self.W[k] * avail[k] for k in avail) / tw
            nbad = sum(1 for v in avail.values() if v < comp["threshold_score"])
            compounded = nbad >= comp["min_surveys"]
            if compounded: h = max(0.0, h - comp["penalty"])
            sev = ("Healthy" if h >= lab["healthy_min"]
                   else "Watch" if h >= lab["watch_min"] else "Critical")
            rows.append({"segment_km": s, "health_score": round(h, 1), "severity": sev,
                         "surveys_present": len(avail), "compounded": compounded,
                         **{f"score_{k.lower()}": round(avail[k], 1) for k in avail}})
        return pd.DataFrame(rows)


if __name__ == "__main__":
    d = os.path.dirname(os.path.abspath(__file__))
    e = ScoringEngine(os.path.join(d, "scoring_config.json"))
    e.ingest_dcvg(pd.read_csv(f"{d}/DCVG_RKPL_SEC2_REAL.csv"))
    e.ingest_ili(pd.read_csv(f"{d}/ILI_anomalies_RKPL_SEC2_REAL.csv"))
    e.ingest_cipl(pd.read_csv(f"{d}/CIPL_ONOFF_RKPL_SEC2_SYNTHETIC.csv"))
    e.ingest_dci(pd.read_csv(f"{d}/DC_INTERFERENCE_RKPL_SEC2_SYNTHETIC.csv"))
    e.ingest_cat(pd.read_csv(f"{d}/CAT_RKPL_SEC2_SYNTHETIC.csv"))
    e.ingest_soil(pd.read_csv(f"{d}/SOIL_RESISTIVITY_RKPL_SEC2_SYNTHETIC.csv"))
    res = e.compute()
    res.to_csv(f"{d}/SEGMENT_HEALTH_SCORES.csv", index=False)
    print(f"Scored {len(res)} segments | KPI: {res['health_score'].mean():.1f} | "
          f"{res['severity'].value_counts().to_dict()}")
    # live-demo: ingest bad CIPL upload and show the diff
    before = res.set_index("segment_km")["health_score"]
    e.ingest_cipl(pd.read_csv(f"{d}/DEMO_UPLOAD_bad_cipl.csv"))
    after = e.compute().set_index("segment_km")["health_score"]
    diff = (after - before).loc[lambda x: x.abs() > 0.05]
    print("What changed after DEMO_UPLOAD_bad_cipl.csv:")
    for k, v in diff.items(): print(f"  Ch {k}: {before[k]} -> {after[k]}  ({v:+.1f})")
