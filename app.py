import streamlit as st
import pandas as pd

from core_pipeline.cache_manager import (
    get_cached_profile_names,
    get_profile_by_name,
    save_profile_to_cache
)

from core_pipeline.brand_engine import generate_brand_profile
from core_pipeline.audit_engine import run_search_terms_audit
from core_pipeline.audit_logger import generate_deep_dive_workbook


# ----------------------------
# PAGE CONFIG
# ----------------------------
st.set_page_config(
    layout="wide",
    page_title="AI PPC Search Terms Auditor"
)


# ----------------------------
# SESSION STATE INIT
# ----------------------------
def init_state():
    defaults = {
        "stage": 1,
        "blueprint": None,
        "audit_results": None,
        "selected_profile": None
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

init_state()


# ----------------------------
# SIDEBAR STATUS
# ----------------------------
st.sidebar.title("Status")
st.sidebar.write(f"Stage: {st.session_state.stage}")


# =========================================================
# STAGE 1 — BLUEPRINT
# =========================================================
if st.session_state.stage == 1:

    st.title("🛡️ Brand Blueprint")
    st.caption("Define semantic boundaries before audit")

    profiles = ["-- New Profile --"] + get_cached_profile_names()
    selected = st.selectbox("Profile", profiles)

    # ----------------------------
    # LOAD EXISTING
    # ----------------------------
    if selected != "-- New Profile --":
        profile = get_profile_by_name(selected)

        st.session_state.blueprint = profile["blueprint"]
        st.session_state.selected_profile = selected

        st.success(f"Loaded: {selected}")

        if st.button("Proceed → Audit"):
            st.session_state.stage = 2
            st.rerun()


    # ----------------------------
    # CREATE NEW
    # ----------------------------
    else:
        st.subheader("Create New Profile")

        col1, col2, col3 = st.columns(3)
        brand = col1.text_input("Brand")
        offering = col2.text_input("Core Offering")
        landing = col3.text_input("Landing Page")

        if st.button("Generate Blueprint") and brand and offering and landing:

            with st.spinner("Generating..."):
                try:
                    st.session_state.blueprint = generate_brand_profile(
                        brand, offering, landing
                    )
                    st.session_state.temp_brand = brand
                    st.session_state.temp_offering = offering

                except Exception as e:
                    st.error(str(e))


        # ----------------------------
        # EDIT BLUEPRINT
        # ----------------------------
        if st.session_state.blueprint:

            bp = st.session_state.blueprint

            st.divider()
            st.subheader("Edit Blueprint")

            variants = st.text_input(
                "Brand Variants",
                ", ".join(bp.get("brand_variants", []))
            )

            negatives = st.text_area(
                "Negative Triggers",
                ", ".join(bp.get("explicit_negative_triggers", []))
            )

            competitors = st.text_area(
                "Competitors",
                ", ".join(bp.get("predicted_competitors", []))
            )

            rule = st.text_input(
                "Golden Rule",
                bp.get("strict_relevance_rule", "")
            )


            if st.button("Save & Continue"):

                final = {
                    "brand_variants": [x.strip() for x in variants.split(",") if x.strip()],
                    "explicit_negative_triggers": [x.strip() for x in negatives.split(",") if x.strip()],
                    "predicted_competitors": [x.strip() for x in competitors.split(",") if x.strip()],
                    "strict_relevance_rule": rule.strip()
                }

                save_profile_to_cache(
                    st.session_state.temp_brand,
                    st.session_state.temp_offering,
                    final
                )

                st.session_state.selected_profile = (
                    f"{st.session_state.temp_brand} | {st.session_state.temp_offering}"
                )

                st.session_state.stage = 2
                st.rerun()


# =========================================================
# STAGE 2 — AUDIT
# =========================================================
elif st.session_state.stage == 2:

    st.title("🔍 Audit Engine")

    st.caption(f"Profile: {st.session_state.selected_profile}")

    if st.button("← Back"):
        st.session_state.stage = 1
        st.session_state.audit_results = None
        st.rerun()


    file = st.file_uploader("Upload CSV", type=["csv"])


    # ----------------------------
    # RUN AUDIT
    # ----------------------------
    if file and st.button("Run Audit"):

        progress = st.progress(0)
        status = st.empty()

        try:
            result = run_search_terms_audit(
                file,
                st.session_state.selected_profile,
                progress_bar_ui=progress,
                status_text_ui=status
            )

            st.session_state.audit_results = result

            status.success("Complete")

        except Exception as e:
            st.error(str(e))


# ----------------------------
# RESULTS
# ----------------------------
if st.session_state.audit_results:

    res = st.session_state.audit_results
    m = res["metrics"]

    st.divider()
    st.subheader("Metrics")

    cols = st.columns(5)

    cols[0].metric("Input Terms", m["total_inputted"])
    cols[1].metric("Relevant Terms", m["relevant_count"])
    cols[2].metric("Irrelevant Terms", m["irrelevant_count"])
    cols[3].metric("Review Queue", m["review_queue_count"])
    cols[4].metric("Total Outputted", m["total_outputted"])

    st.divider()

    st.info(f"Roots Found: {m['roots_found']}")
        st.divider()
        st.subheader("Negative Export")

        st.text_area(
            "Copy/Paste",
            res["copy_paste_notation"],
            height=250
        )

        if st.button("Generate Ledger →"):
            st.session_state.stage = 3
            st.rerun()


# =========================================================
# STAGE 3 — LEDGER
# =========================================================
elif st.session_state.stage == 3:

    st.title("🔬 Audit Ledger")

    if st.button("← Back"):
        st.session_state.stage = 2
        st.rerun()


    if st.session_state.audit_results:

        st.success("Building workbook...")

        try:
            buffer = generate_deep_dive_workbook(
                st.session_state.audit_results
            )

            st.download_button(
                "Download Excel",
                buffer,
                file_name="audit_ledger.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        except Exception as e:
            st.error(str(e))

    else:
        st.info("Run audit first")
