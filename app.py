# --- CRUCIAL CLOUD PATH PATCH (MUST BE LINES 1-3) ---
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import json
import re
from datetime import datetime

# --- RE-MAPPED TO MATCH YOUR EXACT GITHUB FILENAMES ---
from backend_stage1 import run_brand_audit
from backend_stage2 import classify_terms_batch, extract_root_negatives, apply_ads_notation
from backend_stage3 import push_to_google_sheets

# --- INITIAL APP SETUP & STATE MANAGEMENT ---
st.set_page_config(page_title="Negative Keyword Architect", layout="wide")

CACHE_DIR = "brand_cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def get_cached_profiles():
    files = [f for f in os.listdir(CACHE_DIR) if f.endswith('.json')]
    # Sort the files alphabetically before adding the "Create New" option
    sorted_files = sorted([f.replace('.json', '') for f in files], key=str.lower)
    return ["Create New"] + sorted_files

def load_cached_profile(filename):
    with open(os.path.join(CACHE_DIR, f"{filename}.json"), "r") as f:
        return json.load(f)

def save_profile_to_cache(name, data):
    safe_name = name.replace("/", "-").strip()
    with open(os.path.join(CACHE_DIR, f"{safe_name}.json"), "w") as f:
        json.dump(data, f)

if "stage" not in st.session_state:
    st.session_state.stage = 1
if "brand_profile" not in st.session_state:
    st.session_state.brand_profile = None
if "locked_rules" not in st.session_state:
    st.session_state.locked_rules = None
if "audit_results" not in st.session_state:
    st.session_state.audit_results = None

# ==========================================
# 🗺️ PERSISTENT NAVIGATION HUB
# ==========================================
st.title("🛡️ Google Ads Negative Keyworder")
st.write("Google Ads Classification System build on Brand Understanding. A multi-stage tool to streamline PPC maintenance.")

# Visual step-by-step indicator bar
nav_cols = st.columns([1, 4, 1])

with nav_cols[0]:
    # Only show "Back to Stage 1" if we are actually past Stage 1
    if st.session_state.stage > 1:
        if st.button("⬅️ Back to Stage 1", use_container_width=True):
            # --- CLEAN SLATE FLUSH LOGIC ---
            st.session_state.stage = 1
            st.session_state.brand_profile = None
            st.session_state.locked_rules = None
            st.session_state.audit_results = None
            
            # Flush out temporary metadata tracking variables
            if "temp_brand_name" in st.session_state:
                del st.session_state.temp_brand_name
            if "temp_campaign_type" in st.session_state:
                del st.session_state.temp_campaign_type
            if "temp_core_offering" in st.session_state:
                del st.session_state.temp_core_offering
            if "cache_key" in st.session_state:
                del st.session_state.cache_key
                
            st.rerun()

with nav_cols[2]:
    # Only show "Forward to Stage 2" if we have already built/locked a blueprint rule setup
    if st.session_state.stage == 1 and st.session_state.locked_rules is not None:
        if st.button("Forward to Stage 2 ➡️", use_container_width=True):
            st.session_state.stage = 2
            st.rerun()

st.markdown("---")

# ==========================================
# 🔥 STAGE 1: BRAND UNDERSTANDING AUDIT
# ==========================================
if st.session_state.stage == 1:
    st.header("Stage 1: Brand Understanding Audit")
    
    cache_options = get_cached_profiles()
    selected_cache = st.selectbox("Select a Profile Configuration Template", options=cache_options, index=0)
    
    # --- DYNAMIC CONTROLS SWITCH ---
    if selected_cache != "Create New":
        if st.session_state.brand_profile is None:
            try:
                st.session_state.brand_profile = load_cached_profile(selected_cache)
                
                # --- STRATIFIED CACHE PARSING WITH LEGACY PROTECTION ---
                cache_parts = selected_cache.split(" | ")
                if len(cache_parts) == 3:
                    st.session_state.temp_brand_name = cache_parts[0]
                    st.session_state.temp_campaign_type = cache_parts[1]
                    st.session_state.temp_core_offering = cache_parts[2]
                else:
                    # Backward compatibility for old 2-part naming patterns
                    st.session_state.temp_brand_name = cache_parts[0]
                    st.session_state.temp_campaign_type = "Search"
                    st.session_state.temp_core_offering = cache_parts[1] if len(cache_parts) > 1 else ""
                    
                st.session_state.locked_rules = st.session_state.brand_profile
                st.session_state.cache_key = selected_cache
            except Exception as e:
                st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nFailed loading profile asset framework configuration. Details: {str(e)}")
                
        st.success(f"📋 Loaded configuration workspace layout baseline: **{selected_cache}**")
        
    else:
        if st.session_state.get('last_selected_cache') != "Create New" and 'last_selected_cache' in st.session_state:
            st.session_state.brand_profile = None
            
        # --- NEW THREE-COLUMN BALANCED INPUT LAYOUT ---
        col1, col2, col3 = st.columns(3)
        with col1:
            brand_name = st.text_input("Brand Name", value="")
        with col2:
            campaign_type = st.selectbox("Campaign Type", options=["-Please Select-", "Search", "PMax", "Display", "Shopping"])
        with col3:
            core_offering = st.text_input("Core Offering of the Ad Group", value="")
            
        landing_pages = st.text_area(
            "Target Landing Page Links & Context (One link per line)", 
            placeholder="https://client.com/pricing\nhttps://client.com/remarketing-resource",
            height=80
        )
        
        if st.button("Launch Brand Understanding Audit"):
            if not brand_name or campaign_type == "-Please Select-" or not core_offering or not landing_pages:
                st.error("🛑 **Error Code: E001 - Missing Input Parameters**\n\nOne or more required input fields were left blank or unselected. Please specify a valid Brand Name, Campaign Type, Core Offering, and Landing Page dataset to clear systemic validation.")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                try:
                    status_text.text("Connecting to Gemini AI Engine...")
                    progress_bar.progress(25)
                    
                    # Campaign type behaves as a label metadata tag; it is excluded from the core AI parameters text dump
                    raw_profile = run_brand_audit(brand_name, core_offering, landing_pages)
                    progress_bar.progress(75)
                    
                    status_text.text("Structuring core framework rulesets...")
                    st.session_state.brand_profile = raw_profile
                    st.session_state.temp_brand_name = brand_name
                    st.session_state.temp_campaign_type = campaign_type
                    st.session_state.temp_core_offering = core_offering
                    progress_bar.progress(100)
                    
                    status_text.empty()
                    progress_bar.empty()
                    st.rerun()
                    
                except Exception as e:
                    progress_bar.empty()
                    status_text.empty()
                    err_str = str(e).lower()
                    if "429" in err_str or "quota" in err_str:
                        st.error("🛑 **Error Code: E003 - API Quota Exhausted**\n\nThe free-tier API speed limit was hit. Please pause for 60 seconds before clicking resume.")
                    elif "gemini" in err_str:
                        st.error("📡 **Error Code: E004 - Cloud Connection Dropped**\n\nThe connection to the Google Cloud AI loop was dropped mid-process. Please check your network connection and try again.")
                    else:
                        st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nAn unexpected backend processing anomaly occurred. Details: {str(e)}")

    st.session_state.last_selected_cache = selected_cache

    if st.session_state.brand_profile:
        st.markdown("### 📝 Refine Brand Understanding Rulesets")
        st.caption("Double-click individual cells to add custom items, clear rows, or correct terms before cementing absolute rules.")
        
        edited_profile = {}
        
        row1_col1, row1_col2 = st.columns(2)
        with row1_col1:
            st.markdown("#### ✨ Allowed Brand Variants & Misspellings")
            df_bv = pd.DataFrame(st.session_state.brand_profile.get("brand_variants", []), columns=["Brand Variants"])
            ed_bv = st.data_editor(df_bv, num_rows="dynamic", use_container_width=True, key="editor_bv")
            edited_profile["brand_variants"] = ed_bv["Brand Variants"].dropna().tolist()
            
        with row1_col2:
            st.markdown("#### 🛡️ Protected Core Offering Terms (Safety Shield)")
            df_prot = pd.DataFrame(st.session_state.brand_profile.get("protected_terms", []), columns=["Protected Core Terms"])
            ed_prot = st.data_editor(df_prot, num_rows="dynamic", use_container_width=True, key="editor_prot")
            edited_profile["protected_terms"] = ed_prot["Protected Core Terms"].dropna().tolist()
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        row2_col1, row2_col2 = st.columns(2)
        with row2_col1:
            st.markdown("#### 🚨 Competitor Target Brand Names (Red Flags)")
            df_comp = pd.DataFrame(st.session_state.brand_profile.get("competitors", []), columns=["Competitor Brands"])
            ed_comp = st.data_editor(df_comp, num_rows="dynamic", use_container_width=True, key="editor_comp")
            edited_profile["competitors"] = ed_comp["Competitor Brands"].dropna().tolist()
            
        with row2_col2:
            st.markdown("#### ❌ Clear Irrelevant Elements & Concepts")
            df_irr = pd.DataFrame(st.session_state.brand_profile.get("irrelevant_terms", []), columns=["Irrelevant Concepts"])
            ed_irr = st.data_editor(df_irr, num_rows="dynamic", use_container_width=True, key="editor_irr")
            edited_profile["irrelevant_terms"] = ed_irr["Irrelevant Concepts"].dropna().tolist()
            
        st.markdown("---")
        
        if st.button("Confirm Brand Understanding", type="primary"):
            b_title = st.session_state.get("temp_brand_name", "Brand").strip()
            t_title = st.session_state.get("temp_campaign_type", "Search").strip()
            c_title = st.session_state.get("temp_core_offering", "Offering").strip()
            
            # --- INCORPORATING CAMPAIGN TYPE INTO CACHE STRUCTURAL STRING ---
            cache_key = f"{b_title} | {t_title} | {c_title}"
            
            save_profile_to_cache(cache_key, edited_profile)
            
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
    BATCH_SIZE = 25
    
    if uploaded_file:
        try:
            uploaded_file.seek(0)
            df_preview = pd.read_csv(uploaded_file)
            term_col_preview = next((c for c in df_preview.columns if "search term" in c.lower() or "query" in c.lower()), None)
            
            if term_col_preview:
                raw_count = len(df_preview[term_col_preview].dropna().drop_duplicates())
                num_batches = (raw_count + BATCH_SIZE - 1) // BATCH_SIZE
                
                # --- BACKEND CALCULATION: BOTH TIERS ---
                paid_seconds = max(int(num_batches * 1.5), 3)
                if paid_seconds >= 60:
                    paid_display = f"{paid_seconds // 60} min {paid_seconds % 60} sec" if paid_seconds % 60 > 0 else f"{paid_seconds // 60} min"
                else:
                    paid_display = f"{paid_seconds} seconds"
                
                free_seconds = 8 if num_batches <= 1 else 60 + (num_batches * 5)
                if free_seconds >= 60:
                    free_display = f"{free_seconds // 60} min {free_seconds % 60} sec" if free_seconds % 60 > 0 else f"{free_seconds // 60} min"
                else:
                    free_display = f"{free_seconds} seconds"
                
                st.warning(
                    f"📊 **Dataset Loaded:** {raw_count} unique search terms detected ({num_batches} optimized API calls).\n\n"
                    f"⏱️ **Estimated Run Time:** **{paid_display}** ({free_display} if using Free Tier)"
                )
            else:
                st.error("🛑 **Error Code: E005 - System Operational Failure**\n\nMissing Required Column Mapping. The uploaded file must contain a clear column titled either 'Search Term' or 'Query'.")
        except Exception as e:
            st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nFile read breakdown context failure: {str(e)}")

    if st.button("Launch Search Terms Audit"):
        if not uploaded_file:
            st.error("🛑 **Error Code: E002 - Missing File Stream**\n\nThe Search Term Ledger dataset CSV upload path is missing. Please select and load a file before hitting execute.")
        else:
            try:
                uploaded_file.seek(0)
                
                df_input = pd.read_csv(uploaded_file)
                term_col = next((c for c in df_input.columns if "search term" in c.lower() or "query" in c.lower()), None)
                search_terms = df_input[term_col].dropna().drop_duplicates().tolist()
                total_input_count = len(search_terms)
                
                progress_bar = st.progress(0)
                counter_text = st.empty()
                metric_slots = st.columns(4)
                m1, m2, m3, m4 = metric_slots[0].empty(), metric_slots[1].empty(), metric_slots[2].empty(), metric_slots[3].empty()
                
                relevant_list = []
                irrelevant_list = []
                review_list = []
                
                for i in range(0, total_input_count, BATCH_SIZE):
                    batch = search_terms[i:i + BATCH_SIZE]
                    counter_text.text(f"Processing Batch: Terms {i} to {min(i + BATCH_SIZE, total_input_count)} of {total_input_count}...")
                    
                    try:
                        batch_results = classify_terms_batch(batch, st.session_state.locked_rules)
                        
                        for res in batch_results:
                            row_data = {
                                "Search Term": res["search_term"],
                                "Confidence Score": res["confidence"],
                                "Reasoning": res["reason"]
                            }
                            if res["classification"] == "relevant":
                                relevant_list.append(row_data)
                            elif res["classification"] == "irrelevant":
                                irrelevant_list.append(row_data)
                            else:
                                review_list.append(row_data)
                                
                        percent_complete = int((min(i + BATCH_SIZE, total_input_count) / total_input_count) * 100)
                        progress_bar.progress(percent_complete)
                        
                        m1.metric("Processed", f"{min(i + BATCH_SIZE, total_input_count)}")
                        m2.metric("Relevant ✅", f"{len(relevant_list)}")
                        m3.metric("Irrelevant ❌", f"{len(irrelevant_list)}")
                        m4.metric("Review Queue 🔍", f"{len(review_list)}")
                        
                    except Exception as batch_err:
                        err_str = str(batch_err).lower()
                        if "429" in err_str or "quota" in err_str:
                            st.error("🛑 **Error Code: E003 - API Quota Exhausted**\n\nThe free-tier API speed limit was hit. Please pause for 60 seconds before clicking resume.")
                        elif "validation error" in err_str or "eof while parsing" in err_str or "json" in err_str:
                            st.error("⚠️ **Error Code: E006 - Batching Threshold Issue**\n\nThe text data payload in this batch was too large for the AI engine to return completely. The system has automatically safe-stopped. To fix this, change **BATCH_SIZE = 25** to **BATCH_SIZE = 15** at the top of Stage 2 in your app.py file.")
                        elif "gemini" in err_str:
                            st.error("📡 **Error Code: E004 - Cloud Connection Dropped**\n\nThe connection to the Google Cloud AI loop was dropped mid-process. Please check your network connection and try again.")
                        else:
                            st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nAn unexpected processing failure occurred on batch data execution chunk. Details: {str(batch_err)}")
                        st.stop()

                irr_phrases = [r["Search Term"] for r in irrelevant_list]
                saved_phrases = [r["Search Term"] for r in relevant_list] + [r["Search Term"] for r in review_list]
                
                protected_list = st.session_state.locked_rules.get("protected_terms", [])
                
                raw_roots = extract_root_negatives(irr_phrases, saved_phrases, protected_list)
                root_negatives_payload = [
                    {"Root Word": word, "Blocked Volume Count": count, "Ads Notation Match": apply_ads_notation(word, is_exact=False)}
                    for word, count in raw_roots.items()
                ]
                
                final_negatives_output = []
                active_root_words = set(raw_roots.keys())
                
                for rn in root_negatives_payload:
                    final_negatives_output.append(rn["Ads Notation Match"])
                    
                for irr in irrelevant_list:
                    phrase = irr["Search Term"]
                    phrase_words = set(re.findall(r'\b\w+\b', phrase.lower()))
                    
                    protected_words = set()
                    for p_term in protected_list:
                        protected_words.update(re.findall(r'\b\w+\b', p_term.lower()))
                        
                    contains_protected = bool(phrase_words & protected_words)
                    
                    if contains_protected:
                        final_negatives_output.append(apply_ads_notation(phrase, is_exact=True))
                    else:
                        if not (phrase_words & active_root_words):
                            final_negatives_output.append(apply_ads_notation(phrase, is_exact=False))
                            
                final_negatives_output = list(set(final_negatives_output))
                
                total_processed_output = len(relevant_list) + len(irrelevant_list) + len(review_list)
                if total_input_count != total_processed_output:
                    st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nLeakage error structural check broken. Input rows ({total_input_count}) do not match matching total classifications output rows ({total_processed_output}).")
                    st.stop()
                    
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
                st.success("Analysis matrix generated.")
                st.rerun()
                
            except Exception as main_err:
                st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nCore ledger computation failed on analysis layout execution: {str(main_err)}")

if st.session_state.audit_results:
    res_data = st.session_state.audit_results
    
    st.markdown("---")
    st.subheader("📋 Audit Execution Outputs Summary")
    st.write(pd.DataFrame([res_data["metrics"]]))
    
    with st.expander("🔍 Review Queue View & Direct Download", expanded=True):
        df_rev = pd.DataFrame(res_data["review"])
        st.dataframe(df_rev, use_container_width=True)
        if not df_rev.empty:
            st.download_button("Download Raw Review Queue CSV", data=df_rev.to_csv(index=False), file_name="review_queue_dump.csv")
            
    col_out1, col_out2 = st.columns([2, 1])
    with col_out1:
        st.subheader("🎯 Optimization Output: Google Ads Copy-Paste Match List")
        st.caption("Copy this target data string completely straight onto campaign parameters negative target keywords list inputs.")
        text_block = "\n".join(res_data["copy_paste_list"])
        st.text_area("Ready Matrix List Output Data Box", value=text_block, height=350)
        
    with col_out2:
        st.subheader("⚙️ Workspace Controls")
        if st.button("🚀 Download Workbook Ledger", use_container_width=True):
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
                    st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nCloud ledger synchronization pipeline interrupted: {str(e)}")
                    
        if st.button("🔄 Start New Audit", use_container_width=True):
            st.session_state.stage = 1
            st.session_state.brand_profile = None
            st.session_state.locked_rules = None
            st.session_state.audit_results = None
            st.rerun()
