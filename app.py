"""RKPL Pipeline Integrity Health Dashboard — Hackathon Demo.
Run:  streamlit run app.py   (from the folder containing the demo CSVs + scoring_engine.py)
"""
import json
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from scoring_engine import ScoringEngine

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "scoring_config.json")

SURVEY_FILES = {
    "DCVG": ("DCVG_RKPL_SEC2_REAL.csv", "ingest_dcvg"),
    "ILI": ("ILI_anomalies_RKPL_SEC2_REAL.csv", "ingest_ili"),
    "CIPL": ("CIPL_ONOFF_RKPL_SEC2_SYNTHETIC.csv", "ingest_cipl"),
    "DCI": ("DC_INTERFERENCE_RKPL_SEC2_SYNTHETIC.csv", "ingest_dci"),
    "CAT": ("CAT_RKPL_SEC2_SYNTHETIC.csv", "ingest_cat"),
    "SOIL": ("SOIL_RESISTIVITY_RKPL_SEC2_SYNTHETIC.csv", "ingest_soil"),
}
SEV_COLOR = {"Healthy": "#2e7d32", "Watch": "#f9a825", "Critical": "#c62828"}
SURVEY_LABEL = {
    "ILI": "ILI / MFL Pigging", "DCVG": "DCVG (coating)", "CIPL": "CIPL / ON-OFF (CP)",
    "DCI": "DC Interference", "CAT": "Current Attenuation", "SOIL": "Soil Resistivity",
}

# Column fuzzy-matching for uploads: canonical -> accepted aliases
ALIASES = {
    "chainage_km": ["chainage", "chainage (km)", "chainage(km)", "ch_km", "km"],
    "off_potential_v_cse": ["off", "off potential", "instant off", "psp off", "off_v"],
    "on_potential_v_cse": ["on", "on potential", "psp on", "on_v"],
    "positive_swing_mv": ["swing", "swing_mv", "potential swing"],
    "resistivity_ohm_cm": ["resistivity", "soil resistivity"],
    "pct_ir": ["% ir", "ir", "%ir", "pct ir"],
    "defect_chainage_km": ["defect chainage", "defect location chainage"],
    "chainage_from_km": ["chainage from", "chainage from(km)", "chainage_from"],
    "chainage_to_km": ["chainage to", "chainage to(km)", "chainage_to"],
    "depth_pct_wt": ["depth", "depth %", "depth, %", "depth_pct", "depth [%]",
                     "peak depth [%]", "depth (%)", "depth % wt", "d/t %"],
    "erf_b31g": ["erf", "erf (asme b31g)", "erf b31g", "erf (b31g)", "repair factor"],
    "axial_length_mm": ["length", "length [mm]", "length (mm)", "axial length",
                        "axial length [mm]", "length_mm"],
    "width_mm": ["width", "width [mm]", "width (mm)"],
    "wt_mm": ["wt", "wt [mm]", "wall thickness", "wall thickness [mm]",
              "wall thickness (mm)", "nominal wt", "t [mm]"],
    "psafe_kg_cm2": ["psafe", "psafe [kg/cm2]", "safe pressure", "psafe (kg/cm2)"],
    "location_int_ext": ["int/ext", "internal/external", "location", "int_ext",
                         "surface location"],
    "orientation_oclock": ["o'clock", "oclock", "orientation", "o'clock position"],
    "abs_distance_m": ["abs. distance, m", "abs distance", "abs_distance",
                       "log dist. [m]", "log distance [m]", "odometer [m]"],
    "attenuation_mb_per_m": ["attenuation", "attenuation_mb"],
    "chainage_from": ["chainage from"],
    "chainage_to": ["chainage to"],
}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    ren = {}
    for c in df.columns:
        key = str(c).strip().lower()
        for canon, alts in ALIASES.items():
            if key == canon or key in alts:
                ren[c] = canon
                break
    return df.rename(columns=ren)


def detect_survey_type(df: pd.DataFrame) -> str | None:
    cols = set(df.columns)
    if {"depth_pct_wt", "erf_b31g"} & cols and ({"chainage_km"} & cols or {"abs_distance_m"} & cols):
        return "ILI"
    if "pct_ir" in cols:
        return "DCVG"
    if "off_potential_v_cse" in cols:
        return "CIPL"
    if "positive_swing_mv" in cols:
        return "DCI"
    if "attenuation_mb_per_m" in cols:
        return "CAT"
    if "resistivity_ohm_cm" in cols:
        return "SOIL"
    return None


def build_engine(extra: list[tuple[str, pd.DataFrame]]) -> ScoringEngine:
    eng = ScoringEngine(CFG_PATH)
    for stype, (fname, method) in SURVEY_FILES.items():
        p = os.path.join(BASE, fname)
        if os.path.exists(p):
            getattr(eng, method)(pd.read_csv(p))
    for stype, df in extra:
        method = SURVEY_FILES[stype][1]
        kwargs = {}
        if stype == "ILI" and "chainage_km" not in df.columns:
            kwargs["chainage_is_abs_distance"] = True
        getattr(eng, method)(df, **kwargs)
    return eng


def readings_in_segment(seg: float, seg_len: float) -> dict[str, pd.DataFrame]:
    """Raw readings that fall inside [seg, seg+seg_len) per survey, for drill-down."""
    out = {}
    lo, hi = seg, seg + seg_len
    for stype, (fname, _) in SURVEY_FILES.items():
        p = os.path.join(BASE, fname)
        if not os.path.exists(p):
            continue
        df = pd.read_csv(p)
        if stype == "DCVG":
            m = df["defect_chainage_km"].between(lo, hi) | (
                (df["chainage_from_km"] <= lo) & (df["chainage_to_km"] > lo))
        elif stype == "CAT":
            m = (df["chainage_from"] <= lo) & (df["chainage_to"] > lo)
        else:
            m = df["chainage_km"].between(lo, hi)
        sub = df[m]
        if len(sub):
            out[stype] = sub
    # uploaded readings
    for stype, df in st.session_state.get("uploads", []):
        if "chainage_km" in df.columns:
            sub = df[df["chainage_km"].between(lo, hi)]
            if len(sub):
                out[f"{stype} (uploaded)"] = sub
    return out


# ----------------------------------------------------------------------------
st.set_page_config(page_title="RKPL Pipeline Health", layout="wide", page_icon="🛢️")

if "uploads" not in st.session_state:
    st.session_state.uploads = []          # list of (survey_type, df)
if "prev_scores" not in st.session_state:
    st.session_state.prev_scores = None

cfg = json.load(open(CFG_PATH))
pinfo = cfg["pipeline"]

engine = build_engine(st.session_state.uploads)
res = engine.compute()

st.title("🛢️ RKPL Section-2 — Pipeline Integrity Health")
st.caption(f"{pinfo['name']} · Ch {pinfo['start_km']}–{pinfo['end_km']} km · "
           f"{len(res)} × {int(pinfo['segment_length_km']*1000)} m segments · "
           f"6 survey layers, criticality-weighted")

tab_overview, tab_drill, tab_upload, tab_reco, tab_settings = st.tabs(
    ["📊 Overview", "🔍 Segment drill-down", "📤 Upload survey",
     "🔧 Repair recommendation", "⚙️ Settings"])

# ============================ OVERVIEW ============================
with tab_overview:
    kpi = res["health_score"].mean()
    counts = res["severity"].value_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pipeline Health Score", f"{kpi:.1f} / 100")
    c2.metric("Healthy segments", int(counts.get("Healthy", 0)))
    c3.metric("Watch segments", int(counts.get("Watch", 0)))
    c4.metric("Critical segments", int(counts.get("Critical", 0)))

    # chainage strip chart
    fig = go.Figure()
    for sev, color in SEV_COLOR.items():
        sub = res[res["severity"] == sev]
        fig.add_trace(go.Bar(
            x=sub["segment_km"], y=sub["health_score"], name=sev,
            marker_color=color, width=pinfo["segment_length_km"] * 0.95,
            hovertemplate="Ch %{x} km<br>Health %{y}<extra>" + sev + "</extra>"))
    fig.add_hline(y=cfg["severity_labels"]["healthy_min"], line_dash="dot",
                  line_color="#2e7d32", annotation_text="Healthy ≥ 80")
    fig.add_hline(y=cfg["severity_labels"]["watch_min"], line_dash="dot",
                  line_color="#c62828", annotation_text="Critical < 50")
    fig.update_layout(height=340, barmode="overlay", bargap=0,
                      xaxis_title="Route chainage (km)", yaxis_title="Health score",
                      yaxis_range=[0, 105], legend_orientation="h",
                      margin=dict(t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Sections to monitor")
    worst = res.nsmallest(10, "health_score").copy()
    score_cols = [c for c in worst.columns if c.startswith("score_")]
    st.dataframe(
        worst[["segment_km", "health_score", "severity", "surveys_present",
               "compounded"] + score_cols],
        use_container_width=True, hide_index=True)

    if st.session_state.prev_scores is not None:
        prev = st.session_state.prev_scores.set_index("segment_km")["health_score"]
        cur = res.set_index("segment_km")["health_score"]
        diff = (cur - prev).dropna()
        changed = diff[diff.abs() > 0.05].sort_values()
        if len(changed):
            st.subheader("🔔 What changed after last upload")
            for seg, dv in changed.items():
                arrow = "🔻" if dv < 0 else "🔺"
                st.markdown(
                    f"{arrow} **Ch {seg} km**: {prev[seg]:.1f} → {cur[seg]:.1f} "
                    f"({dv:+.1f}) — now **{res.set_index('segment_km').loc[seg,'severity']}**")

# ============================ DRILL-DOWN ============================
with tab_drill:
    seg = st.selectbox(
        "Segment (worst first)",
        res.sort_values("health_score")["segment_km"].tolist(),
        format_func=lambda s: (
            f"Ch {s:.1f} km — {res.set_index('segment_km').loc[s,'health_score']:.1f} "
            f"({res.set_index('segment_km').loc[s,'severity']})"))
    row = res.set_index("segment_km").loc[seg]

    st.markdown(f"### Ch {seg:.1f}–{seg + pinfo['segment_length_km']:.1f} km — "
                f"**{row['health_score']:.1f} / 100** "
                f":{'green' if row['severity']=='Healthy' else 'orange' if row['severity']=='Watch' else 'red'}[{row['severity']}]")
    if row["compounded"]:
        st.error("⚠️ Multi-survey confirmation: ≥2 surveys independently flag this "
                 "segment (−10 compounding penalty applied). High-confidence defect.")

    # transparent weight math
    st.subheader("Score composition (transparent weight math)")
    W = cfg["weights"]
    parts = []
    for k in W:
        col = f"score_{k.lower()}"
        if col in row.index and pd.notna(row[col]):
            parts.append({"Survey": SURVEY_LABEL[k], "Score": row[col], "Weight": W[k]})
    pdf_ = pd.DataFrame(parts)
    tw = pdf_["Weight"].sum()
    pdf_["Normalized weight"] = (pdf_["Weight"] / tw).round(3)
    pdf_["Contribution"] = (pdf_["Score"] * pdf_["Normalized weight"]).round(1)
    st.dataframe(pdf_, use_container_width=True, hide_index=True)
    base = pdf_["Contribution"].sum()
    pen = 10 if row["compounded"] else 0
    st.markdown(f"Weighted average = **{base:.1f}**"
                + (f" − {pen} compounding penalty = **{row['health_score']:.1f}**" if pen else ""))

    # raw readings + map
    st.subheader("Raw readings in this segment")
    rd = readings_in_segment(seg, pinfo["segment_length_km"])
    if not rd:
        st.info("No point readings inside this segment — scored from span coverage "
                "(healthy span / CAT attenuation).")
    lat, lon = None, None
    for stype, sub in rd.items():
        st.markdown(f"**{stype}**")
        st.dataframe(sub, use_container_width=True, hide_index=True)
        for latc, lonc in [("latitude", "longitude")]:
            if latc in sub.columns and sub[latc].notna().any():
                lat, lon = sub[latc].dropna().iloc[0], sub[lonc].dropna().iloc[0]
    if lat is not None:
        st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), zoom=12)

# ============================ UPLOAD ============================
with tab_upload:
    st.markdown(
        "Upload a **CSV/XLSX** survey file (PDF parsing runs in the FastAPI backend; "
        "CSV is the reliable demo path). Survey type is auto-detected from columns. "
        "Try `DEMO_UPLOAD_bad_cipl.csv`")
    up = st.file_uploader("Survey file", type=["csv", "xlsx"])
    if up is not None:
        df = pd.read_excel(up) if up.name.endswith("xlsx") else pd.read_csv(up)
        df = normalize_columns(df)
        stype = detect_survey_type(df)
        if stype is None:
            st.error("Could not detect survey type from columns. Expected one of: "
                     "%IR (DCVG), depth/ERF (ILI), OFF potential (CIPL), "
                     "swing (DCI), attenuation (CAT), resistivity (SOIL).")
        else:
            if stype == "ILI":
                from reco_bridge import enrich_ili_with_erf
                df, n_calc = enrich_ili_with_erf(df, cfg)
                if n_calc:
                    st.info(f"Vendor ERF column not found — computed ERF/Psafe for "
                            f"{n_calc} defect(s) using the app's B31G (Original) engine "
                            f"with {cfg['pipe']['grade']}, MAOP {cfg['pipe']['maop_kg_cm2']} kg/cm².")
            st.success(f"Detected **{SURVEY_LABEL[stype]}** — {len(df)} readings. Preview:")
            st.dataframe(df.head(15), use_container_width=True, hide_index=True)
            if st.button("✅ Confirm & ingest", type="primary"):
                st.session_state.prev_scores = res.copy()
                st.session_state.uploads.append((stype, df))
                st.rerun()
    if st.session_state.uploads:
        st.markdown("**Ingested uploads this session:** "
                    + ", ".join(f"{SURVEY_LABEL[s]} ({len(d)} rows)"
                                for s, d in st.session_state.uploads))
        if st.button("Reset session uploads"):
            st.session_state.uploads = []
            st.session_state.prev_scores = None
            st.rerun()

# ============================ REPAIR RECOMMENDATION ============================
with tab_reco:
    from reco_bridge import KGCM2_TO_MPA, recommend_for_row

    st.markdown(
        "**ASME B31G-2012 Level 1 (Original + Modified)** assessment → "
        "governing disposition → permitted repair methods (ASME PCC-2 / "
        "B31.4 / API 1104) → RKPL field SOP checklist. Deterministic: "
        "formulas + static tables, no AI in the decision path. "
        "Engine validated against LIN SCAN's own B31G values (Original "
        "method, X65) — comparison shown per anomaly.")
    p = cfg["pipe"]
    st.caption(f"Pipe: {p['grade']} · OD {p['outside_diameter_mm']} mm · "
               f"MAOP {p['maop_kg_cm2']} kg/cm² · F={p['design_factor']} · "
               f"WT taken per-feature from ILI listing. "
               f"⚠️ Confirm grade/MAOP from pipetally (see scoring_config.json).")

    # ---- Manual / what-if entry --------------------------------------
    with st.expander("✏️ Manual entry / what-if check (dummy data)", expanded=False):
        from integrity_reco.models import DefectRecord, DefectType, LeakStatus
        from integrity_reco.recommend import recommend as _reco
        from reco_bridge import pipe_from_cfg
        mc1, mc2, mc3 = st.columns(3)
        m_d = mc1.number_input("Depth (% of WT)", 0.0, 100.0, 45.0, 1.0)
        m_L = mc2.number_input("Axial length (mm)", 1.0, 5000.0, 200.0, 10.0)
        m_wt = mc3.number_input("Wall thickness (mm)", 1.0, 30.0, 7.2, 0.1)
        mc4, mc5, mc6 = st.columns(3)
        m_ie = mc4.selectbox("Location", ["External", "Internal"])
        m_leak = mc5.selectbox("Leak status", ["non_leaking", "leaking"])
        m_int = mc6.checkbox("Interacting cluster")
        m_weld = mc6.checkbox("Within 25 mm of weld")
        if st.button("Assess dummy defect", type="primary"):
            dd = DefectRecord(
                defect_id="WHATIF-001",
                defect_type=(DefectType.INTERNAL_METAL_LOSS if m_ie == "Internal"
                             else DefectType.EXTERNAL_METAL_LOSS),
                depth_pct=m_d, length_mm=m_L,
                leak_status=LeakStatus(m_leak),
                interacting=m_int, near_weld=m_weld, source="manual")
            wcard = _reco(dd, pipe_from_cfg(cfg, m_wt))
            wdisp = wcard["disposition"]
            wcol = {"acceptable_monitor": "green", "acceptable": "green",
                    "not_acceptable": "orange", "immediate_repair": "red",
                    "out_of_level1_scope": "violet"}.get(wdisp, "gray")
            st.markdown(f"#### :{wcol}[{wdisp.replace('_',' ').upper()}] — "
                        f"{wcard['governing_method']}")
            w1, w2 = st.columns(2)
            w1.metric("Governing ERF",
                      f"{wcard['erf']:.3f}" if wcard["erf"] else "n/a")
            wps = wcard["safe_pressure_mpa"]
            w2.metric("Psafe", f"{wps/KGCM2_TO_MPA:.1f} kg/cm²" if wps else "n/a")
            st.info(f"**Required action:** {wcard['required_action']['action']}")
            st.markdown("**Permitted repairs:** " + ("; ".join(
                o["method"] for o in wcard["permitted_repair_options"])
                or "— (escalation required, see action)"))
            with st.expander("Full calculation detail"):
                st.json(wcard["assessments"])
            st.download_button("⬇️ What-if card (JSON)",
                               json.dumps(wcard, indent=2, default=str),
                               file_name="whatif_card.json")

    # collect ILI rows: baseline file + any session-uploaded ILI
    ili_frames = []
    _ili_path = os.path.join(BASE, SURVEY_FILES["ILI"][0])
    if os.path.exists(_ili_path):
        try:
            ili_frames.append(pd.read_csv(_ili_path))
        except Exception as e:
            st.warning(f"Baseline ILI file could not be read: {e}")
    ili_frames += [d for s, d in st.session_state.uploads if s == "ILI"]

    if not ili_frames:
        st.info("No ILI data loaded — the baseline ILI CSV is not present and "
                "no ILI file has been uploaded this session. Use the "
                "**manual what-if entry above** to assess a defect, or upload "
                "an ILI CSV in the 📤 Upload tab.")
        ili_all = pd.DataFrame()
    else:
        ili_all = pd.concat(ili_frames, ignore_index=True)

    needed = {"depth_pct_wt", "axial_length_mm", "wt_mm", "chainage_km"}
    missing = needed - set(ili_all.columns) if len(ili_all) else set()
    if len(ili_all) and missing:
        st.error(f"ILI data missing required columns for B31G: {sorted(missing)}. "
                 "No assessment performed (no guessing).")
    elif len(ili_all):
        ili_all = ili_all.dropna(subset=list(needed)).reset_index(drop=True)
        if ili_all.empty:
            st.info("ILI rows found, but none have all four required values "
                    "(depth, length, WT, chainage). Use manual entry above.")
        else:
            labels = [f"#{i:03d} · Ch {r.chainage_km:.3f} km · "
                      f"{r.location_int_ext} · d={r.depth_pct_wt:.0f}% · "
                      f"L={r.axial_length_mm:.0f} mm"
                      for i, r in ili_all.iterrows()]
            pick = st.selectbox("ILI anomaly", range(len(ili_all)),
                                format_func=lambda i: labels[i])
            row = ili_all.iloc[pick]
            card = recommend_for_row(row, pick, cfg)

            disp = card["disposition"]
            colour = {"acceptable_monitor": "green", "acceptable": "green",
                      "not_acceptable": "orange", "immediate_repair": "red",
                      "out_of_level1_scope": "violet"}.get(disp, "gray")
            st.markdown(f"### :{colour}[{disp.replace('_',' ').upper()}] — "
                        f"governing: {card['governing_method']}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Governing ERF", f"{card['erf']:.3f}" if card["erf"] else "n/a")
            ps = card["safe_pressure_mpa"]
            c2.metric("Psafe", f"{ps/KGCM2_TO_MPA:.1f} kg/cm²" if ps else "n/a")
            vc = card.get("vendor_comparison")
            if vc:
                ok = vc.get("match_within_2pct")
                c3.metric("Vendor ERF (LIN SCAN)", f"{vc['vendor_erf']:.3f}",
                          delta=("engine match ✓" if ok else "MISMATCH — verify"),
                          delta_color="normal" if ok else "inverse")

            st.info(f"**Required action:** {card['required_action']['action']}  \n"
                    f"*Ref: {card['required_action']['reference']}*")

            with st.expander("Calculation detail (auditable, both methods)"):
                for name, a in card["assessments"].items():
                    st.markdown(f"**{a['method']}** — `{a['formula_branch']}`")
                    st.json({k: a[k] for k in ("d_over_t", "z_param", "folias_m",
                                               "flow_stress_mpa",
                                               "failure_pressure_mpa",
                                               "safe_pressure_mpa", "erf",
                                               "standard_reference", "notes")})
                if vc:
                    st.json({"vendor_comparison": vc})

            st.subheader("Permitted repair options (standards layer)")
            for o in card["permitted_repair_options"]:
                st.markdown(f"- **{o['method']}** — {o['constraints']}  \n"
                            f"  *Ref: {o['reference']}*")

            st.subheader("Field verification & rectification checklist")
            for j, s in enumerate(card["field_verification_and_sop"]):
                tag = "🟦 Site SOP" if s["basis"] == "Site SOP" else "🟨 Standard"
                st.checkbox(f"{tag} — {s['step']}  *({s['reference']})*",
                            key=f"sop_{pick}_{j}")

            st.warning("  \n".join(f"• {c}" for c in card["caveats"]))
            st.download_button("⬇️ Download recommendation card (JSON)",
                               json.dumps(card, indent=2, default=str),
                               file_name=f"reco_{pick:03d}.json")

# ============================ SETTINGS ============================
with tab_settings:
    st.markdown("Edit criticality weights live — the whole pipeline rescores instantly. "
                "Weights are renormalized over surveys present per segment.")
    new_w = {}
    cols = st.columns(3)
    for i, (k, v) in enumerate(cfg["weights"].items()):
        new_w[k] = cols[i % 3].slider(SURVEY_LABEL[k], 0.0, 1.0, float(v), 0.05)
    c1, c2 = st.columns(2)
    if c1.button("Apply weights", type="primary"):
        cfg["weights"] = new_w
        json.dump(cfg, open(CFG_PATH, "w"), indent=2)
        st.rerun()
    if c2.button("Restore defaults"):
        cfg["weights"] = {"ILI": 0.35, "DCVG": 0.20, "CIPL": 0.20,
                          "DCI": 0.10, "CAT": 0.10, "SOIL": 0.05}
        json.dump(cfg, open(CFG_PATH, "w"), indent=2)
        st.rerun()
    st.caption("Scoring thresholds live in scoring_config.json (per-survey bands); "
               "edit the file to tune them — no code change needed.")
