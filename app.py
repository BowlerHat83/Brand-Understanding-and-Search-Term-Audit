import streamlit as st
import pandas as pd
import io

from core_pipeline.cache_manager import (
    get_cached_profile_names,
    get_profile_by_name,
    save_profile_to_cache
)
from core_pipeline.brand_engine import generate_brand_profile
from core_pipeline.audit_engine import run_search_terms_audit
from core_pipeline.audit_logger import generate_deep_dive_workbook

st.set_page_config(layout="wide", page_title="AI PPC Search Terms Auditor")

# ----------------------------
# Session State Init
# ----------------------------
defaults = {
    "current_blueprint": None,
    "audit_results": None,
    "active_stage": 1
}

for k, v in defaults.items():
    st.session_state.setdefault(k, v)

st.sidebar.title("Navigation Tracker")
st.sidebar.info(f"📍 Stage {st.session_state.active_stage}")

# ----------------------------
# STAGE 1 — BRAND BLUEPRINT
# ----------------------------
if st.session_state.active_stage == 1:
    st.title("🛡️ Stage 1: Brand Blueprint")
    st.caption("Define commercial boundaries before auditing.")

    cached = get_cached_profile_names()
    options = ["-- Create New Profile --"] + cached

    selected = st.selectbox("Select or create profile:", options)

    # ----------------------------
    # Load existing profile
    # ----------------------------
    if selected != "-- Create New Profile --":
        data = get_profile_by_name(selected)
        st.session_state.current_blueprint = data["blueprint"]
        st.session_state.selected_profile_key = selected

        st.success(f"Loaded profile: {selected}")

        if st.button("Proceed to Audit ➜", type="primary"):
            st.session_state.active_stage = 2
            st.rerun()

    # ----------------------------
    # Create new profile
    # ----------------------------
    else:
        st.write("---")
        st.subheader("New Profile")

        c1, c2, c3 = st.columns(3)
        brand = c1.text_input("Brand")
        offering = c2.text_input("Core Offering")
        landing = c3.text_input("Landing Page")

        if st.button("Generate Profile", type="primary"):
            if brand and offering and landing:
                with st.spinner("Generating blueprint..."):
                    try:
                        st.session_state.current_blueprint = generate_brand_profile(
                            brand, offering, landing
                        )
                    except Exception as e:
                        st.error(f"Blueprint error: {e}")
            else:
                st.error("All fields required.")

        # ----------------------------
        # Edit blueprint
        # ----------------------------
        if st.session_state.current_blueprint:
            st.write("---")
            st.subheader("Edit Blueprint (Final Truth)")

            bp = st.session_state.current_blueprint

            variants = st.text_input(
                "Brand Variants",
                value=", ".join(bp.get("brand_variants", []))
            )

            negatives = st.text_area(
                "Negative Triggers",
                value=", ".join(bp.get("explicit_negative_triggers", []))
            )

            competitors = st.text_area(
                "Competitors",
                value=", ".join(bp.get("predicted_competitors", []))
            )

            rule = st.text_input(
                "Golden Rule",
                value=bp.get("strict_relevance_rule", "")
            )

            if st.button("Save Profile"):
                final = {
                    "brand_variants": [x.strip() for x in variants.split(",") if x.strip()],
                    "explicit_negative_triggers": [x.strip() for x in negatives.split(",") if x.strip()],
                    "predicted_competitors": [x.strip() for x in competitors.split(",") if x.strip()],
                    "strict_relevance_rule": rule.strip()
                }

                save_profile_to_cache(brand, offering, final)

                st.session_state.selected_profile_key = f"{brand.strip()} | {offering.strip()}"
                st.session_state.active_stage = 2
                st.success("Profile saved.")
                st.rerun()

# ----------------------------
# STAGE 2 — AUDIT
# ----------------------------
elif st.session_state.active_stage == 2:
    st.title("🔍 Stage 2: Audit")

    st.caption(f"Profile: {st.session_state.selected_profile_key}")

    if st.button("← Back"):
        st.session_state.active_stage = 1
        st.session_state.audit_results = None
        st.rerun()

    file = st.file_uploader("Upload CSV", type=["csv"])

    if file and st.button("Run Audit", type="primary"):
        pbar = st.progress(0.0)
        status = st.empty()

        try:
            result = run_search_terms_audit(
                file,
                st.session_state.selected_profile_key,
                progress_bar_ui=pbar,
                status_text_ui=status
            )

            st.session_state.audit_results = result
            status.success("Audit complete")

        except RuntimeError as e:
            status.empty()
            pbar.empty()

            msg = str(e)

            if "429" in msg:
                st.error("Rate limit hit")
                st.info("Retrying safely...")
            elif "503" in msg:
                st.error("Service issue")
            else:
                st.error(msg)

        except Exception as e:
            status.empty()
            pbar.empty()
            st.error(f"Unexpected error: {e}")

    # ----------------------------
    # Results
    # ----------------------------
    if st.session_state.audit_results:
        res = st.session_state.audit_results
        m = res["metrics"]

        st.write("---")
        st.subheader("Metrics")

        cols = st.columns(4)
        cols[0].metric("Input", m["total_inputted"])
        cols[1].metric("Relevant", m["relevant_count"])
        cols[2].metric("Irrelevant", m["irrelevant_count"])
        cols[3].metric("Review", m["review_queue_count"])

        if m["integrity_check_passed"]:
            st.success(f"Integrity OK ({m['total_outputted']})")
        else:
            st.error("Integrity mismatch")

        st.info(
            f"Roots: {m['roots_found']} | "
            f"Absorbed: {m['terms_absorbed_by_roots']}"
        )

        st.write("---")
        st.subheader("Review Queue")

        if m["review_queue_count"]:
            df = pd.DataFrame(
                res["review_queue_data"],
                columns=["Search Terms"]
            )
            st.dataframe(df)

            st.download_button(
                "Download Review CSV",
                df.to_csv(index=False).encode("utf-8"),
                file_name="review_queue.csv"
            )
        else:
            st.success("No review items")

        st.write("---")
        st.subheader("Negative Export")

        st.text_area("Copy/Paste", res["copy_paste_notation"], height=250)

        st.write("---")

        if st.button("Deep Dive Ledger"):
            st.session_state.active_stage = 3
            st.rerun()

# ----------------------------
# STAGE 3 — LEDGER
# ----------------------------
elif st.session_state.active_stage == 3:
    st.title("🔬 Ledger")

    if st.button("← Back"):
        st.session_state.active_stage = 2
        st.rerun()

    if st.session_state.audit_results:
        st.success("Generating workbook...")

        try:
            buffer = generate_deep_dive_workbook(st.session_state.audit_results)

            st.download_button(
                "Download Excel Ledger",
                buffer,
                file_name="audit_ledger.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        except Exception as e:
            st.error(f"Failed: {e}")
    else:
        st.info("Run audit first")
