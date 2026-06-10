import streamlit as st
import pandas as pd

from core.stage1_brand import (
    generate_brand_profile,
    list_cached_blueprints,
    load_cached_blueprint
)

from core.stage2_audit import run_stage2_audit
from core.stage3_export import export_to_excel
from core.root_negatives import extract_root_negatives


# ----------------------------
# PAGE CONFIG
# ----------------------------
st.set_page_config(
    layout="wide",
    page_title="AI PPC Search Terms Auditor"
)


# ----------------------------
# SESSION STATE
# ----------------------------
def init_state():
    defaults = {
        "stage": 1,
        "blueprint": None,
        "audit_results": None,
        "root_negatives": None,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

init_state()


# =========================================================
# STAGE 1 — BRAND BLUEPRINT
# =========================================================
cached = list_cached_blueprints()

st.title("🛡️ Brand Blueprint")

if st.session_state.stage == 1:

    selection = st.selectbox(
        "Select Existing Blueprint",
        ["-- Create New --"] + cached
    )

    # ----------------------------
    # LOAD EXISTING BLUEPRINT
    # ----------------------------
    if selection != "-- Create New --":

        blueprint = load_cached_blueprint(selection)

        if blueprint:
            st.session_state.blueprint = blueprint
            st.success(f"Loaded cached blueprint: {selection}")

            if st.button("Continue → Audit"):
                st.session_state.stage = 2
                st.rerun()

    # ----------------------------
    # CREATE NEW BLUEPRINT
    # ----------------------------
    else:

        brand = st.text_input("Brand Name")
        offering = st.text_input("Core Offering")
        landing = st.text_input("Landing Page")

        if st.button("Generate Blueprint"):

            if not brand or not offering or not landing:
                st.error("Please fill all fields")
            else:
                blueprint = generate_brand_profile(brand, offering, landing)

                st.session_state.blueprint = blueprint
                st.session_state.brand = brand

                st.success("Blueprint generated")

                if st.button("Continue → Audit"):
                    st.session_state.stage = 2
                    st.rerun()


# =========================================================
# STAGE 2 — AUDIT ENGINE
# =========================================================
elif st.session_state.stage == 2:

    st.title("🔍 Audit Engine")

    if st.button("← Back"):
        st.session_state.stage = 1
        st.rerun()

    file = st.file_uploader("Upload Google Ads Search Terms CSV", type=["csv"])

    # ----------------------------
    # RUN AUDIT
    # ----------------------------
    if file and st.button("Run Audit"):

        df = pd.read_csv(file)

        # assume first column contains search terms
        search_terms = df.iloc[:, 0].dropna().astype(str).tolist()

        with st.spinner("Running AI audit..."):

            results = run_stage2_audit(
                search_terms,
                st.session_state.blueprint,
                batch_size=30
            )

            st.session_state.audit_results = results

        st.success("Audit complete")

    # ----------------------------
    # RESULTS PREVIEW
    # ----------------------------
    if st.session_state.audit_results:

        df = pd.DataFrame(st.session_state.audit_results)

        st.subheader("Results Preview")
        st.dataframe(df)

        st.metric("Total Terms", len(df))
        st.metric("Relevant", len(df[df["classification"] == "relevant"]))
        st.metric("Irrelevant", len(df[df["classification"] == "irrelevant"]))
        st.metric("Review", len(df[df["classification"] == "review"]))

        # ----------------------------
        # ROOT NEGATIVES (preview)
        # ----------------------------
        st.subheader("Root Negatives Preview")

        try:
            roots = extract_root_negatives(st.session_state.audit_results)
            st.session_state.root_negatives = roots
            st.write(roots)
        except Exception as e:
            st.warning(f"Root negatives failed: {e}")

        if st.button("Generate Excel →"):
            st.session_state.stage = 3
            st.rerun()


# =========================================================
# STAGE 3 — EXPORT
# =========================================================
elif st.session_state.stage == 3:

    st.title("📊 Export Ledger")

    if st.button("← Back"):
        st.session_state.stage = 2
        st.rerun()

    if st.session_state.audit_results:

        with st.spinner("Building Excel file..."):

            file_path = export_to_excel(
                st.session_state.audit_results,
                root_negatives=st.session_state.root_negatives or []
            )

        st.success("Workbook ready")

        with open(file_path, "rb") as f:
            st.download_button(
                "Download Excel",
                f,
                file_name="ppc_audit.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    else:
        st.info("Run an audit first")
