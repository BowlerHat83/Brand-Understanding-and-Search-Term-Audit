import streamlit as st
import pandas as pd
import io

from core_pipeline.cache_manager import get_cached_profile_names, get_profile_by_name, save_profile_to_cache
from core_pipeline.brand_engine import generate_brand_profile
from core_pipeline.audit_engine import run_search_terms_audit
from core_pipeline.audit_logger import generate_deep_dive_workbook

st.set_page_config(layout="wide", page_title="AI PPC Search Terms Auditor")

if "current_blueprint" not in st.session_state:
    st.session_state.current_blueprint = None
if "audit_results" not in st.session_state:
    st.session_state.audit_results = None
if "active_stage" not in st.session_state:
    st.session_state.active_stage = 1

st.sidebar.title("Navigation Tracker")
st.sidebar.info(f"📍 **Current Stage Focus:** Stage {st.session_state.active_stage}")

# --- STAGE 1: BRAND UNDERSTANDING BLUEPRINT ---
if st.session_state.active_stage == 1:
    st.title("🛡️ Stage 1: Brand Understanding Blueprint")
    st.caption("Establish the absolute strategic parameters of your offering before running search term audits.")
    
    cached_profiles = get_cached_profile_names()
    options = ["-- Create New Profile --"] + cached_profiles
    selected_option = st.selectbox("Choose an existing Brand Profile or build a new one:", options)

    if selected_option != "-- Create New Profile --":
        cached_data = get_profile_by_name(selected_option)
        st.session_state.current_blueprint = cached_data["blueprint"]
        st.session_state.selected_profile_key = selected_option
        
        st.success(f"🔓 **Fast-Track Active:** Successfully loaded approved ruleset for '{selected_option}'.")
        if st.button("Proceed Directly to Search Terms Audit ➔", type="primary"):
            st.session_state.active_stage = 2
            st.rerun()
    else:
        st.write("---")
        st.subheader("📋 New Profile Configuration")
        col1, col2, col3 = st.columns(3)
        brand_name = col1.text_input("Brand Name", placeholder="e.g., Apex Solar")
        core_offering = col2.text_input("Ad Group Core Offering", placeholder="e.g., Commercial Solar Installations")
        landing_page = col3.text_input("Landing Page Link / Domain", placeholder="e.g., apexsolar.com/b2b")

        if st.button("Draft Initial Profile via AI Assistant", type="primary"):
            if brand_name and core_offering and landing_page:
                with st.spinner("AI is analyzing industry vectors and generating ruleset..."):
                    ai_draft = generate_brand_profile(brand_name, core_offering, landing_page)
                    st.session_state.current_blueprint = ai_draft
            else:
                st.error("Please fill out Brand Name, Core Offering, and Landing Page to build a new profile.")

        if st.session_state.current_blueprint:
            st.write("---")
            st.subheader("🛠️ Review & Modify Blueprint Rules (The Absolute Truth)")
            
            bp = st.session_state.current_blueprint
            edited_variants = st.text_input("Protected Brand Variants (Comma separated):", value=", ".join(bp.get("brand_variants", [])))
            edited_negatives = st.text_area("Explicit Negative Triggers (Comma separated):", value=", ".join(bp.get("explicit_negative_triggers", [])))
            edited_competitors = st.text_area("Predicted Industry Competitors (Comma separated):", value=", ".join(bp.get("predicted_competitors", [])))
            edited_rule = st.text_input("Golden Rule of Relevance Description:", value=bp.get("strict_relevance_rule", ""))

            if st.button("Approve Changes & Save Profile to Cache"):
                final_blueprint = {
                    "brand_variants": [x.strip() for x in edited_variants.split(",") if x.strip()],
                    "explicit_negative_triggers": [x.strip() for x in edited_negatives.split(",") if x.strip()],
                    "predicted_competitors": [x.strip() for x in edited_competitors.split(",") if x.strip()],
                    "strict_relevance_rule": edited_rule.strip()
                }
                save_profile_to_cache(brand_name, core_offering, final_blueprint)
                st.session_state.selected_profile_key = f"{brand_name.strip()} | {core_offering.strip()}"
                st.success(f"🎉 Stored custom profile under key: **{st.session_state.selected_profile_key}**")
                st.session_state.active_stage = 2
                st.rerun()

# --- STAGE 2: SEARCH TERMS AUDIT (STANDARD OUTPUTS + METRICS & PROGRESS) ---
elif st.session_state.active_stage == 2:
    st.title("🔍 Stage 2: Search Terms Audit & Extraction")
    st.caption(f"Active Profile Target: **{st.session_state.selected_profile_key}**")
    
    if st.button("⬅ Return to Stage 1"):
        st.session_state.active_stage = 1
        st.session_state.audit_results = None
        st.rerun()
        
    st.write("---")
    uploaded_file = st.file_uploader("Upload your raw Google Ads Search Terms report (CSV Format):", type=["csv"])

    if uploaded_file and st.button("Run Audit Engine & Safety Verification", type="primary"):
        # COSMETIC UPGRADE: Draw placeholder containers for progress tracking elements
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        
        # ERROR HANDLING MATRIX: Watch execution for pipeline faults
        try:
            results = run_search_terms_audit(
                uploaded_file, 
                st.session_state.selected_profile_key,
                progress_bar_ui=progress_bar,
                status_text_ui=status_text
            )
            st.session_state.audit_results = results
            status_text.success("🚀 Complete! Audit processing calculations finalized successfully.")
            
        except RuntimeError as runtime_err:
            # Catch custom domain engine faults (Quota limits, API crashes)
            status_text.empty()
            progress_bar.empty()
            
            err_msg = str(runtime_err)
            if "ERR_GEMINI_QUOTA_EXCEEDED" in err_msg:
                st.error("🛑 **API RATE LIMIT EXCEEDED (Error Code: 429)**")
                st.warning(
                    "The application sent too many keywords too quickly for your Google AI tier. "
                    "Please wait exactly 60 seconds to reset your token window, then click run again."
                )
            elif "ERR_GEMINI_SERVER_BREAK" in err_msg:
                st.error("💥 **GOOGLE GEMINI ENGINE FAILURE**")
                st.info("Google's backend model experienced an internal glitch. Please retry the execution or check Google AI Studio's API status page.")
            else:
                st.error(f"❌ **CRITICAL RUNTIME ERROR:** {err_msg}")
                
        except Exception as global_err:
            status_text.empty()
            progress_bar.empty()
            st.error(f"🚨 **UNEXPECTED PIPELINE CRASH:** {str(global_err)}")

    # Render standard UI layout components
    if st.session_state.audit_results:
        res = st.session_state.audit_results
        metrics = res["metrics"]

        st.write("---")
        st.subheader("🛡️ Data Integrity & Lineage Metrics")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Inputted Terms", f"{metrics['total_inputted']:,}")
        c2.metric("Routed to Relevant", f"{metrics['relevant_count']:,}")
        c3.metric("Routed to Irrelevant", f"{metrics['irrelevant_count']:,}")
        c4.metric("Emergency Review Queue", f"{metrics['review_queue_count']:,}")

        if metrics["integrity_check_passed"]:
            st.success(f"✅ Data Security Check Passed: Inputted count matches Outputted count perfectly ({metrics['total_outputted']:,}). No terms were lost.")
        else:
            st.error("🚨 Critical Error: Data mismatch identified between ingestion pipeline steps.")

        st.info(f"⚡ **Optimization Multiplier:** Isolated **{metrics['roots_found']} single-word Root Negatives** which successfully automated **{metrics['terms_absorbed_by_roots']} complex search phrase variations**.")

        st.write("---")
        st.subheader("⚠️ Review Queue Outliers")
        st.markdown("The terms below experienced lower confidence scores and are ready for download.")
        
        if metrics["review_queue_count"] > 0:
            review_df = pd.DataFrame(res["review_queue_data"], columns=["Isolated Search Terms for Manual Review"])
            st.dataframe(review_df, use_container_width=True)
            
            csv_data = review_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Review Queue CSV",
                data=csv_data,
                file_name="ppc_review_queue_outliers.csv",
                mime="text/csv"
            )
        else:
            st.success("The review queue is completely empty! All terms were classified with absolute structural certainty.")

        st.write("---")
        st.subheader("📋 Google Ads Notation Negative List")
        st.text_area(
            label="Ready for Bulk Import (Single words are broad match, phrases get quotes):",
            value=res["copy_paste_notation"],
            height=250
        )
        
        st.write("---")
        st.subheader("⚖️ Auditability & Accountability Deep-Dive")
        if st.button("🔬 Show Understanding Breakdown"):
            st.session_state.active_stage = 3
            st.rerun()

st.header("🔬 Stage 3: The Accountability & Knowledge Ledger")

if (
    "audit_results" in st.session_state
    and st.session_state.audit_results is not None
):

    st.success(
        "✨ Search terms audit complete! Your deep-dive workbook is compiled."
    )

    audit_data = st.session_state.audit_results

    try:

        buffer = generate_deep_dive_workbook(audit_data)

        st.download_button(
            label="📥 Download Complete Accountability Ledger (.xlsx)",
            data=buffer,
            file_name="ppc_audit_ledger.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )

        st.info(
            "💡 Tip: This file is fully compatible with Google Sheets."
        )

    except Exception as e:
        st.error(
            f"Failed to generate download file: {str(e)}"
        )

else:
    st.info(
        "Waiting for Stage 2 to complete processing."
    )


