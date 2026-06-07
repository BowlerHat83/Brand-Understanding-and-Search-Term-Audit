import streamlit as pd
import streamlit as st
import pandas as pd
import io

# Import our custom isolated core modules
from core_pipeline.cache_manager import get_cached_profile_names, get_profile_by_name, save_profile_to_cache
from core_pipeline.brand_engine import generate_brand_profile
from core_pipeline.audit_engine import run_search_terms_audit
from core_pipeline.audit_logger import generate_deep_dive_workbook

st.set_page_config(layout="wide", page_title="AI PPC Search Terms Auditor")

# --- INITIALIZE STATE ENGINES ---
if "current_blueprint" not in st.session_state:
    st.session_state.current_blueprint = None
if "audit_results" not in st.session_state:
    st.session_state.audit_results = None
if "active_stage" not in st.session_state:
    st.session_state.active_stage = 1  # Standard navigation tracker

st.sidebar.title("Navigation Tracker")
st.sidebar.info(f"📍 **Current Stage Focus:** Stage {st.session_state.active_stage}")

# --- STAGE 1: BRAND UNDERSTANDING BLUEPRINT ---
if st.session_state.active_stage == 1:
    st.title("🛡️ Stage 1: Brand Understanding Blueprint")
    st.caption("Establish the absolute strategic parameters of your offering before running search term audits.")
    
    cached_profiles = get_cached_profile_names()
    options = ["-- Create New Profile --"] + cached_profiles
    selected_option = st.selectbox("Choose an existing Brand Profile or build a new one:", options)

    # Pathway B: Fast-Track Dropout Cache Selection
    if selected_option != "-- Create New Profile --":
        cached_data = get_profile_by_name(selected_option)
        st.session_state.current_blueprint = cached_data["blueprint"]
        st.session_state.selected_profile_key = selected_option
        
        st.success(f"🔓 **Fast-Track Active:** Successfully bypassed generation. Loaded approved ruleset for '{selected_option}'.")
        if st.button("Proceed Directly to Search Terms Audit ➔", type="primary"):
            st.session_state.active_stage = 2
            st.rerun()

    # Pathway A: Manual Generation & Interactive Editing Matrix
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

        # Rendering the Editing Matrix (User edits are the Absolute Truth)
        if st.session_state.current_blueprint:
            st.write("---")
            st.subheader("🛠️ Review & Modify Blueprint Rules (The Absolute Truth)")
            st.caption("Modify the terms below to fit your strategy before locking them into the system.")

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
                
                # Advance stage
                st.session_state.active_stage = 2
                st.balloons()
                st.rerun()

# --- STAGE 2: SEARCH TERMS AUDIT (STANDARD OUTPUTS) ---
elif st.session_state.active_stage == 2:
    st.title("🔍 Stage 2: Search Terms Audit & Extraction")
    st.caption(f"Active Profile Target: **{st.session_state.selected_profile_key}**")
    
    if st.button("⬅ Return to Stage 1"):
        st.session_state.active_stage = 1
        st.session_state.audit_results = None
        st.rerun()
        
    st.write("---")
    uploaded_file = st.file_saver = st.file_uploader("Upload your raw Google Ads Search Terms report (CSV Format):", type=["csv"])

    if uploaded_file and st.button("Run Audit Engine & Safety Verification", type="primary"):
        with st.spinner("Executing line-by-line micro-batch calculations..."):
            # Execute pipeline logic securely isolated from UI
            results = run_search_terms_audit(uploaded_file, st.session_state.selected_profile_key)
            st.session_state.audit_results = results

    # Render standard UI outputs if calculations exist in session state memory
    if st.session_state.audit_results:
        res = st.session_state.audit_results
        metrics = res["metrics"]

        st.write("---")
        # Block 1: The Security Metrics Audit Dashboard
        st.subheader("🛡️ Data Integrity & Lineage Metrics")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Inputted Terms", f"{metrics['total_inputted']:,}")
        c2.metric("Routed to Relevant", f"{metrics['relevant_count']:,}")
        c3.metric("Routed to Irrelevant", f"{metrics['irrelevant_count']:,}")
        c4.metric("Emergency Review Queue", f"{metrics['review_queue_count']:,}")

        # Strict Integrity Lineage check block
        if metrics["integrity_check_passed"]:
            st.success(f"✅ Data Security Check Passed: Inputted count perfectly matches Outputted count ({metrics['total_outputted']:,}). No terms were lost.")
        else:
            st.error("🚨 Critical Error: Data mismatch identified between ingestion pipeline steps.")

        st.info(f"⚡ **Optimization Multiplier:** Isolated **{metrics['roots_found']} single-word Root Negatives** which successfully absorbed and automated **{metrics['terms_absorbed_by_roots']} complex search phrase variations**.")

        # Block 2: Review Queue Isolated Download Area
        st.write("---")
        st.subheader("⚠️ Review Queue Outliers")
        st.markdown("The terms below experienced lower confidence scores. They have been safely separated so they don't break your production environment.")
        
        if metrics["review_queue_count"] > 0:
            review_df = pd.DataFrame(res["review_queue_data"], columns=["Isolated Search Terms for Manual Review"])
            st.dataframe(review_df, use_container_width=True)
            
            # Formulate the quick CSV download byte array stream
            csv_data = review_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Review Queue CSV",
                data=csv_data,
                file_name="ppc_review_queue_outliers.csv",
                mime="text/csv"
            )
        else:
            st.success("The review queue is completely empty! All terms were classified with absolute structural certainty.")

        # Block 3: Google Ads Notation Copy Box
        st.write("---")
        st.subheader("📋 Google Ads Notation Negative List")
        st.caption("Copy the field contents below directly into your Google Ads Shared Library Negative Lists or Google Ads Editor.")
        
        st.text_area(
            label="Ready for Bulk Import (Single words are broad match, phrases get quotes):",
            value=res["copy_paste_notation"],
            height=250
        )
        
        # --- TRIGGER ACCOUNTABILITY UNDERSTANDING (STAGE 3 BREAKOUT VALVE) ---
        st.write("---")
        st.subheader("⚖️ Auditability & Accountability Deep-Dive")
        st.markdown(
            "Are you concerned with the classification accuracy or unsure why the AI flagged certain rows? "
            "Trigger a deep-dive knowledge breakdown to verify the reasoning metrics behind every single evaluation row."
        )
        if st.button("🔬 Show Understanding Breakdown"):
            st.session_state.active_stage = 3
            st.rerun()

# --- STAGE 3: KNOWLEDGE UNDERSTANDING DEEP-DIVE LOGS ---
elif st.session_state.active_stage == 3:
    st.title("🔬 Stage 3: Accountability & Knowledge Audit Breakdown")
    st.caption("Deep-dive transparency logs displaying step-by-step reasoning values and confidence metadata scores.")

    if st.button("⬅ Return to Active Stage 2 Workspace"):
        st.session_state.active_stage = 2
        st.rerun()

    st.write("---")
    st.subheader("📊 Generate Transparency Ledger Workbook")
    st.markdown(
        "Click the button below to compile a multi-tab Google Sheets compatible Excel workbook. "
        "This sheet contains a full line-by-line explanation for every keyword processed, alongside its "
        "corresponding confidence score rating values."
    )

    if st.session_state.audit_results:
        with st.spinner("Compiling multi-tab structural sheets..."):
            # Pass our saved audit dictionary down to our Stage 3 Excel sheet builder module
            excel_bytes_buffer = generate_deep_dive_workbook(st.session_state.audit_results)
            
            st.download_button(
                label="📥 Download Complete AI Understanding Ledger (.XLSX)",
                data=excel_bytes_buffer,
                file_name="ppc_audit_accountability_ledger.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
            
        st.write("---")
        st.markdown("""
        ### How to ingest this file into Google Sheets:
        1. Download the `.xlsx` file using the blue button above.
        2. Open your Google Drive account.
        3. Click **New ➔ File Upload** and select this ledger.
        4. Open the uploaded sheet; Google Sheets will automatically render it across four clean tabs:
           * `1. Relevant Terms` (Includes AI Confidence Scores)
           * `2. Review Queue` (Includes AI Confidence Scores)
           * `3. Irrelevant Terms` (Includes AI Confidence Scores)
           * `4. Root Negatives` (Pure Frequency Analytics Engine Log)
        """)
    else:
        st.error("No search terms audit memory state was found. Please return to Stage 2 and run a fresh report processing run first.")
