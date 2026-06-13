import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime

# Import your backend modules
from stage1_brand import run_brand_audit
from stage2_audit import classify_single_term, extract_root_negatives, apply_ads_notation
from stage3_sheets import push_to_google_sheets

# --- INITIAL APP SETUP & STATE MANAGEMENT ---
st.set_page_config(page_title="Negative Keyword Architect", layout="wide")

# Directory setup for simulating local caching mechanism
CACHE_DIR = "brand_cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# Helper functions for the caching matrix
def get_cached_profiles():
    files = [f for f in os.listdir(CACHE_DIR) if f.endswith('.json')]
    return ["Create New"] + [f.replace('.json', '') for f in files]

def load_cached_profile(filename):
    with open(os.path.join(CACHE_DIR, f"{filename}.json"), "r") as f:
        return json.load(f)

def save_profile_to_cache(name, data):
    # Standardize cache name format: 'Brand Name | Core Offering'
    safe_name = name.replace("/", "-").strip()
    with open(os.path.join(CACHE_DIR, f"{safe_name}.json"), "w") as f:
        json.dump(data, f)

# Initialize Session States for multi-stage tracking
if "stage" not in st.session_state:
    st.session_state.stage = 1
if "brand_profile" not in st.session_state:
    st.session_state.brand_profile = None
if "locked_rules" not in st.session_state:
    st.session_state.locked_rules = None
if "audit_results" not in st.session_state:
    st.session_state.audit_results = None

# --- MAIN APP LAYOUT HEADER ---
st.title("🛡️ Google Ads Negative Keyword Architect")
st.write("Streamlining Search Term Reports (STR) with Human-in-the-Loop Validation.")
st.markdown("---")

# ==========================================
# 🔥 STAGE 1: BRAND UNDERSTANDING AUDIT
# ==========================================
if st.session_state.stage == 1:
    st.header("Stage 1: Brand Understanding Audit")
    
    # Check cache options
    cache_options = get_cached_profiles()
    selected_cache = st.selectbox("Select a Profile Configuration Template", options=cache_options, index=0)
    
    # Input layouts
    col1, col2 = st.columns(2)
    with col1:
        brand_name = st.text_input("Brand Name", value="" if selected_cache == "Create New" else selected_cache.split(" | ")[0])
    with col2:
        core_offering = st.text_input("Core Offering of the Ad Group", value="" if selected_cache == "Create New" else selected_cache.split(" | ")[1])
        
    landing_page = st.text_input("Target Landing Page Link/Context")
    
    # Actions for setting up the profile matrix
    if selected_cache != "Create New" and st.button("Load Profile Baseline"):
        try:
            st.session_state.brand_profile = load_cached_profile(selected_cache)
            st.info("Cached profile successfully loaded into memory workspace below.")
        except Exception as e:
            st.error(f"Error Code: E005 - App Error. Failed loading profile asset: {str(e)}")

    # Audit Button Execution Hook
    if st.button("Launch Brand Understanding Audit"):
        # Explicit input data validation blocks
        if not brand_name:
            st.error("Error Code: E001 - Missing Input: 'Brand Name' is required to launch.")
        elif not core_offering:
            st.error("Error Code: E001 - Missing Input: 'Core Offering' is required to launch.")
        elif not landing_page:
            st.error("Error Code: E001 - Missing Input: 'Landing Page Link' is required to launch.")
        else:
            # Replaces button with simulated progressive load experience
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            try:
                status_text.text("Connecting to Gemini AI Engine...")
                progress_bar.progress(25)
                
                # Fetch baseline analysis blueprint ruleset from Backend
                raw_profile = run_brand_audit(brand_name, core_offering, landing_page)
                progress_bar.progress(75)
                
                status_text.text("Structuring core framework rulesets...")
                st.session_state.brand_profile = raw_profile
                progress_bar.progress(100)
                
                status_text.empty()
                progress_bar.empty()
                st.rerun()
                
            except Exception as e:
                progress_bar.empty()
                status_text.empty()
                if "429" in str(e).lower() or "quota" in str(e).lower():
                    st.error("Error Code: E003 - Gemini Quota Exceeded. Please wait before retrying.")
                elif "gemini" in str(e).lower():
                    st.error("Error Code: E004 - Gemini General API Error. Communication loop broken.")
                else:
                    st.error(f"Error Code: E005 - App Error. Details: {str(e)}")

    # --- HUMAN-IN-THE-LOOP ADJUSTMENT WORKSPACE ---
    if st.session_state.brand_profile:
        st.markdown("### 📝 Refine Brand Understanding Rulesets")
        st.caption("Double-click individual rows to make corrections or add custom keywords before cementing absolute truth rules.")
        
        edited_profile = {}
        c1, c2 = st.columns(2)
        with c1:
            df_bv = pd.DataFrame(st.session_state.brand_profile.get("brand_variants", []), columns=["Brand Variants"])
            ed_bv = st.data_editor(df_bv, num_rows="dynamic", use_container_width=True)
            edited_profile["brand_variants"] = ed_bv["Brand Variants"].dropna().tolist()
            
            df_comp = pd.DataFrame(st.session_state.brand_profile.get("competitors", []), columns=["Competitor Brands"])
            ed_comp = st.data_editor(df_comp, num_rows="dynamic", use_container_width=True)
            edited_profile["competitors"] = ed_comp["Competitor Brands"].dropna().tolist()
            
        with c2:
            df_prot = pd.DataFrame(st.session_state.brand_profile.get("protected_terms", []), columns=["Protected Core Terms"])
            ed_prot = st.data_editor(df_prot, num_rows="dynamic", use_container_width=True)
            edited_profile["protected_terms"] = ed_prot["Protected Core Terms"].dropna().tolist()
            
            df_irr = pd.DataFrame(st.session_state.brand_profile.get("irrelevant_terms", []), columns=["Irrelevant Concepts"])
            ed_irr = st.data_editor(df_irr, num_rows="dynamic", use_container_width=True)
            edited_profile["irrelevant_terms"] = ed_irr["Irrelevant Concepts"].dropna().tolist()
            
        if st.button("Confirm Brand Understanding"):
            # Cache using naming standard structure 'Brand Name | Core Offering'
            cache_key = f"{brand_name.strip()} | {core_offering.strip()}"
            save_profile_to_cache(cache_key, edited_profile)
            
            # Formally lock down metrics rule matrices across scope states
            st.session_state.locked_rules = edited_profile
            st.session_state.cache_key = cache_key
            st.session_state.stage = 2
            st.success("Absolute truth established and cached. Transitioning to Stage 2...")
            st.rerun()

# ==========================================
# 📊 STAGE 2: SEARCH TERMS AUDIT
# ==========================================
elif st.session_state.stage == 2:
    st.header(f"Stage 2: Audit Engine — Workspace: {st.session_state.cache_key}")
    
    uploaded_file = st.file_uploader("Upload Search Term Export (CSV Format)", type=["csv"])
    
    if st.button("Launch Search Terms Audit"):
        if not uploaded_file:
            st.error("Error Code: E002 - Search Term CSV ledger missing. Please upload your dataset.")
        else:
            try:
                # Load search term column safely
                df_input = pd.read_csv(uploaded_file)
                # Attempt standard variations of Google Ads report naming formats
                term_col = next((c for c in df_input.columns if "search term" in c.lower() or "query" in c.lower()), None)
                
                if not term_col:
                    st.error("Error Code: E005 - App Error. Could not automatically isolate a 'Search Term' column mapping.")
                    st.stop()
                    
                search_terms = df_input[term_col].dropna().drop_duplicates().tolist()
                total_input_count = len(search_terms)
                
                # Dynamic visual containers
                progress_bar = st.progress(0)
                counter_text = st.empty()
                metric_slots = st.columns(4)
                
                m1 = metric_slots[0].empty()
                m2 = metric_slots[1].empty()
                m3 = metric_slots[2].empty()
                m4 = metric_slots[3].empty()
                
                relevant_list = []
                irrelevant_list = []
                review_list = []
                
                # --- INDIVIDUAL LOOP TESTING PROCESSBLOCK ---
                for idx, term in enumerate(search_terms):
                    try:
                        res = classify_single_term(term, st.session_state.locked_rules)
                        
                        row_data = {
                            "Search Term": term,
                            "Confidence Score": res["confidence"],
                            "Reasoning": res["reason"]
                        }
                        
                        if res["classification"] == "relevant":
                            relevant_list.append(row_data)
                        elif res["classification"] == "irrelevant":
                            irrelevant_list.append(row_data)
                        else:
                            review_list.append(row_data)
                            
                        # Continually dynamic metrics data state streaming output logic
                        percent_complete = int(((idx + 1) / total_input_count) * 100)
                        progress_bar.progress(percent_complete)
                        counter_text.text(f"Processing Matrix Data: {idx + 1} / {total_input_count} Terms Evaluated.")
                        
                        m1.metric("Total Parsed", f"{idx + 1}")
                        m2.metric("Relevant ✅", f"{len(relevant_list)}")
                        m3.metric("Irrelevant ❌", f"{len(irrelevant_list)}")
                        m4.metric("Review Queue 🔍", f"{len(review_list)}")
                        
                    except Exception as e:
                        # Direct catch loops within continuous pipelines
                        if "429" in str(e).lower() or "quota" in str(e).lower():
                            st.error("Error Code: E003 - Gemini Quota Exceeded during stream execution.")
                        else:
                            st.error(f"Error Code: E004/E005 - Internal Stream Issue on term '{term}': {str(e)}")
                        st.stop()

                # --- POST PROCESS ENGINE EXECUTION (ROOT EXTRAS) ---
                irr_phrases = [r["Search Term"] for r in irrelevant_list]
                saved_phrases = [r["Search Term"] for r in relevant_list] + [r["Search Term"] for r in review_list]
                
                # Pure Python extraction math block Execution
                raw_roots = extract_root_negatives(irr_phrases, saved_phrases)
                
                root_negatives_payload = [
                    {"Root Word": word, "Blocked Volume Count": count, "Ads Notation Match": apply_ads_notation(word)}
                    for word, count in raw_roots.items()
                ]
                
                # Determine absolute copy-paste ready negative lists structures
                final_negatives_output = []
                active_root_words = set(raw_roots.keys())
                
                # Add roots first
                for rn in root_negatives_payload:
                    final_negatives_output.append(rn["Ads Notation Match"])
                    
                # Add isolated single phrases NOT blocked by any generated root word phrase
                for irr in irrelevant_list:
                    phrase = irr["Search Term"]
                    phrase_words = set(phrase.lower().split())
                    # Check if any root negative is part of this phrase
                    if not (phrase_words & active_root_words):
                        final_negatives_output.append(apply_ads_notation(phrase))
                
                # Deduplicate entries safely
                final_negatives_output = list(set(final_negatives_output))
                
                # Audit reconciliation check balance calculations
                total_processed_output = len(relevant_list) + len(irrelevant_list) + len(review_list)
                
                if total_input_count != total_processed_output:
                    st.error(f"Error Code: E005 - Reconciliation Error: Input count ({total_input_count}) vs Output count ({total_processed_output}) mismatch. Term leakage occurred.")
                    st.stop()
                    
                # Package everything to store inside the master state architecture session
                st.session_state.audit_results = {
                    "metrics": {
                        "Total Inputted Terms": total_input_count,
                        "Relevant Terms": len(relevant_list),
                        "Irrelevant Terms": len(irrelevant_list),
                        "Review Queue Terms": len(review_list),
                        "Extracted Roots Count": len(root_negatives_payload)
                    },
                    "relevant": relevant_list,
                    "irrelevant": irrelevant_list,
                    "review": review_list,
                    "roots": root_negatives_payload,
                    "copy_paste_list": final_negatives_output
                }
                st.success("Classification matrix engine complete.")
                
            except Exception as main_err:
                st.error(f"Error Code: E005 - App Error. Operational analysis loop failure: {str(main_err)}")

    # --- PRESENTING RESULTS LAYOUTS ---
    if st.session_state.audit_results:
        res_data = st.session_state.audit_results
        
        st.markdown("---")
        st.subheader("📋 Audit Execution Outputs Summary")
        
        # Display Finalized Metrics Logs
        st.write(pd.DataFrame([res_data["metrics"]]))
        
        # Review Queue Layout Tab Sections
        with st.expander("🔍 Review Queue View & Direct Download", expanded=True):
            df_rev = pd.DataFrame(res_data["review"])
            st.dataframe(df_rev, use_container_width=True)
            if not df_rev.empty:
                st.download_button("Download Raw Review Queue CSV", data=df_rev.to_csv(index=False), file_name="review_queue_dump.csv")
                
        # Copy/Paste Output Layout Split Box View
        col_out1, col_out2 = st.columns([2, 1])
        with col_out1:
            st.subheader("🎯 Optimization Output: Google Ads Copy-Paste Match List")
            st.caption("Copy this target data string completely straight onto campaign parameters negative target keywords list inputs.")
            text_block = "\n".join(res_data["copy_paste_list"])
            st.text_area("Ready Matrix List Output Data Box", value=text_block, height=350)
            
        with col_out2:
            st.subheader("⚙️ Workspace Controls")
            # STAGE 3 PIPELINE DEPLOYMENT ACTION
            if st.button("🚀 Download Workbook Ledger", use_container_width=True):
                # Build compilation payload parameters for direct drive injections
                payload = {
                    "Metrics Data": [{"Metric Name": k, "Value": v} for k, v in res_data["metrics"].items()],
                    "Relevant Search Terms": res_data["relevant"],
                    "Irrelevant Search Terms": res_data["irrelevant"],
                    "Review Queue": res_data["review"],
                    "Root Negatives": res_data["roots"]
                }
                
                with st.spinner("Provisioning real-time Google Sheet asset structure..."):
                    try:
                        direct_url = push_to_google_sheets(st.session_state.cache_key, payload)
                        st.success("Google Sheets Asset generated successfully!")
                        st.markdown(f"[🔗 Click to Open Your Google Sheet Workspace]({direct_url})")
                    except Exception as e:
                        st.error(f"Error Code: E005 - App Error. Cloud push failure: {str(e)}")
                        
            if st.button("🔄 Start New Audit", use_container_width=True):
                # Hard flush tracking metrics states to wipe layout cleanly back down
                st.session_state.stage = 1
                st.session_state.brand_profile = None
                st.session_state.locked_rules = None
                st.session_state.audit_results = None
                st.rerun()
