# --- CRUCIAL CLOUD PATH PATCH (MUST BE LINES 1-3) ---
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import json
import re
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# --- RE-MAPPED TO MATCH YOUR EXACT GITHUB FILENAMES ---
from backend_stage1 import run_brand_audit
from backend_stage2 import classify_terms_batch, extract_root_negatives, apply_ads_notation
from backend_stage3 import push_to_google_sheets

# --- INITIAL APP SETUP & STATE MANAGEMENT ---
st.set_page_config(page_title="Negative Keyword Architect", layout="wide")

st.markdown("""
    <style>
        div[data-testid="stDataFrame"] div[role="gridcell"] {
            padding: 4px 10px !important;
        }
        .metric-bold-label {
            font-size: 1.1rem;
            font-weight: 700;
            margin-bottom: 2px;
        }
        .metric-bold-value {
            font-size: 2rem;
            font-weight: 800;
            color: #1E88E5;
        }
    </style>
""", unsafe_allow_html=True)

# --- BULLETPROOF GOOGLE SHEETS CACHE LAYER ---
def get_gspread_client():
    """Authenticates using your existing Stage 3 service account secrets."""
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def safe_split_cell(cell_value):
    """Splits comma-separated text safely, stripping whitespace and empty items."""
    if not cell_value:
        return []
    clean_value = str(cell_value).strip("[]\"'")
    return [item.strip() for item in clean_value.split(",") if item.strip()]

def get_cached_profiles():
    """Pulls all available brand profile names from the Google Sheet rows."""
    try:
        gc = get_gspread_client()
        sheet = gc.open_by_key(st.secrets["CACHE_SPREADSHEET_ID"]).sheet1
        records = sheet.get_all_records()
        
        profile_names = [row["Profile Name"] for row in records if row.get("Profile Name")]
        return ["Create New"] + sorted(profile_names, key=str.lower)
    except Exception:
        return ["Create New"]

def load_cached_profile(profile_name):
    """Finds the matching row, safely handling human-edited text formatting."""
    try:
        gc = get_gspread_client()
        sheet = gc.open_by_key(st.secrets["CACHE_SPREADSHEET_ID"]).sheet1
        records = sheet.get_all_records()
        
        for row in records:
            if str(row["Profile Name"]).strip() == str(profile_name).strip():
                return {
                    "brand_variants": safe_split_cell(row.get("Brand Variants", "")),
                    "protected_terms": safe_split_cell(row.get("Protected Terms", "")),
                    "competitors": safe_split_cell(row.get("Competitors", "")),
                    "irrelevant_terms": safe_split_cell(row.get("Irrelevant Terms", "")),
                    "allowed_languages": safe_split_cell(row.get("Allowed Languages", "English"))
                }
        return None
    except Exception as e:
        st.error(f"Failed to fetch profile from cloud sheet: {str(e)}")
        return None

def save_profile_to_cache(name, data):
    """Saves lists as clean, human-readable comma-separated strings."""
    gc = get_gspread_client()
    sheet = gc.open_by_key(st.secrets["CACHE_SPREADSHEET_ID"]).sheet1
    records = sheet.get_all_records()
    
    row_payload = [
        name,
        ", ".join(data.get("brand_variants", [])),
        ", ".join(data.get("protected_terms", [])),
        ", ".join(data.get("competitors", [])),
        ", ".join(data.get("irrelevant_terms", [])),
        ", ".join(data.get("allowed_languages", ["English"]))
    ]
    
    row_index = None
    for idx, row in enumerate(records, start=2):
        if str(row["Profile Name"]).strip() == str(name).strip():
            row_index = idx
            break
            
    if row_index:
        sheet.update(range_name=f"A{row_index}:F{row_index}", values=[row_payload])
    else:
        sheet.append_row(row_payload)
# --- END CACHE LAYER ---

def is_foreign_script(text):
    """
    Detects if a string contains non-Latin/non-Western characters.
    Allows standard English characters, numbers, spaces, and common punctuation.
    """
    if re.search(r'[^\x00-\x7F\u00C0-\u017F\s\d.,&\'"\-_+/()!]', text):
        return True
    return False

if "stage" not in st.session_state:
    st.session_state.stage = 1
if "brand_profile" not in st.session_state:
    st.session_state.brand_profile = None
if "locked_rules" not in st.session_state:
    st.session_state.locked_rules = None
if "audit_results" not in st.session_state:
    st.session_state.audit_results = None
if "audit_running" not in st.session_state:
    st.session_state.audit_running = False

# ==========================================
# 🗺️ PERSISTENT NAVIGATION HUB
# ==========================================
st.title("🛡️ Google Ads Negative Keyworder")
st.write("Google Ads Classification System built on an expanding Brand Knowledge Base.")

nav_cols = st.columns([1, 4, 1])

with nav_cols[0]:
    if st.session_state.stage > 1:
        if st.button("⬅️ Back to Stage 1", use_container_width=True, disabled=st.session_state.audit_running):
            st.session_state.stage = 1
            st.session_state.brand_profile = None
            st.session_state.locked_rules = None
            st.session_state.audit_results = None
            
            if "temp_brand_name" in st.session_state:
                del st.session_state.temp_brand_name
            if "temp_campaign_type" in st.session_state:
                del st.session_state.temp_campaign_type
            if "temp_ad_group_name" in st.session_state:
                del st.session_state.temp_ad_group_name
            if "temp_core_offering" in st.session_state:
                del st.session_state.temp_core_offering
            if "cache_key" in st.session_state:
                del st.session_state.cache_key
                
            st.rerun()

with nav_cols[2]:
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
    unique_brands = set()
    for option in cache_options:
        if option != "Create New":
            parts = option.split(" | ")
            unique_brands.add(parts[0].strip())
            
    brand_list = ["-Please Select-", "Create New"] + sorted(list(unique_brands), key=str.lower)
    col_b1, col_b2 = st.columns(2)
    
    with col_b1:
        selected_brand_tier = st.selectbox("🏢 Select Brand Portfolio", options=brand_list, index=0)
        
    selected_cache = "Create New"
    
    with col_b2:
        if selected_brand_tier not in ["-Please Select-", "Create New"]:
            matching_workspaces = []
            for option in cache_options:
                if option.startswith(f"{selected_brand_tier} | "):
                    workspace_suffix = option.replace(f"{selected_brand_tier} | ", "").strip()
                    matching_workspaces.append(workspace_suffix)
            
            workspace_options = ["-Please Select-"] + sorted(matching_workspaces, key=str.lower)
            selected_workspace_tier = st.selectbox("🎯 Select Active Campaign / Ad Group Workspace", options=workspace_options, index=0)
            
            if selected_workspace_tier != "-Please Select-":
                selected_cache = f"{selected_brand_tier} | {selected_workspace_tier}"
            else:
                selected_cache = "-Please Select-"
        else:
            st.selectbox("🎯 Select Active Campaign Workspace", options=["N/A - Choose Portfolio Entry"], disabled=True)
    
    st.markdown("---")
    
    if selected_cache == "-Please Select-" or selected_brand_tier == "-Please Select-":
        st.info("👋 Please select a valid Brand Portfolio and Ad Group Workspace to load parameters, or choose 'Create New'.")
        st.session_state.brand_profile = None
        st.session_state.locked_rules = None

    elif selected_cache != "Create New":
        if st.session_state.brand_profile is None or st.session_state.get('cache_key') != selected_cache:
            try:
                st.session_state.brand_profile = load_cached_profile(selected_cache)
                cache_parts = selected_cache.split(" | ")
                st.session_state.temp_brand_name = cache_parts[0]
                st.session_state.temp_campaign_type = cache_parts[1] if len(cache_parts) > 1 else "Search"
                st.session_state.temp_ad_group_name = cache_parts[2] if len(cache_parts) > 2 else ""
                st.session_state.locked_rules = st.session_state.brand_profile
                st.session_state.cache_key = selected_cache
            except Exception as e:
                st.error(f"🔧 **Error Code: E005**\n\nFailed loading profile framework: {str(e)}")
                
        st.success(f"📋 Loaded configuration workspace layout baseline: **{selected_cache}**")
        
        row1_left, row1_right = st.columns(2)
        with row1_left:
            st.selectbox("Brand Name", options=[st.session_state.temp_brand_name], disabled=True)
        with row1_right:
            st.selectbox("Campaign Type", options=[st.session_state.temp_campaign_type], disabled=True)
            
        row2_left, row2_right = st.columns(2)
        with row2_left:
            st.selectbox("Ad Group Name", options=[st.session_state.temp_ad_group_name], disabled=True)
        with row2_right:
            st.text_input("Core Offering of the Ad Group", value="Loaded from Cache Base", disabled=True)

    else:
        if st.session_state.get('last_selected_cache') and st.session_state.get('last_selected_cache') not in ["Create New", "-Please Select-"]:
            st.session_state.brand_profile = None
            st.session_state.locked_rules = None
            
        row1_left, row1_right = st.columns(2)
        with row1_left:
            brand_name = st.text_input("Brand Name", value="")
        with row1_right:
            campaign_type = st.selectbox("Campaign Type", options=["-Please Select-", "Search", "PMax", "Display", "Shopping"])
            
        row2_left, row2_right = st.columns(2)
        with row2_left:
            ad_group_name = st.text_input("Ad Group Name", value="", placeholder="e.g., Competitor_Conversions")
        with row2_right:
            core_offering = st.text_input("Core Offering of the Ad Group", value="", placeholder="What is this ad group selling?")
            
        landing_pages = st.text_area(
            "Target Landing Page Links & Context (One link per line)", 
            placeholder="https://client.com/pricing",
            height=120
        )
        
        if st.button("Launch Brand Understanding Audit"):
            if not brand_name or campaign_type == "-Please Select-" or not ad_group_name or not core_offering or not landing_pages:
                st.error("🛑 **Error Code: E001 - Missing Input Parameters**\n\nPlease satisfy all input configurations and select valid choices.")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                try:
                    status_text.text("Connecting to Gemini AI Engine...")
                    progress_bar.progress(25)
                    
                    raw_profile = run_brand_audit(brand_name, core_offering, landing_pages)
                    progress_bar.progress(75)
                    
                    status_text.text("Structuring core framework rulesets...")
                    st.session_state.brand_profile = raw_profile
                    st.session_state.temp_brand_name = brand_name
                    st.session_state.temp_campaign_type = campaign_type
                    st.session_state.temp_ad_group_name = ad_group_name
                    st.session_state.temp_core_offering = core_offering
                    progress_bar.progress(100)
                    
                    status_text.empty()
                    progress_bar.empty()
                    st.rerun()
                    
                except Exception as e:
                    progress_bar.empty()
                    status_text.empty()
                    st.error(f"🔧 **Error Code: E005**\n\nAn unexpected processing error occurred: {str(e)}")

    st.session_state.last_selected_cache = selected_cache

    if st.session_state.brand_profile:
        st.markdown("### 📝 Refine Brand Understanding Rulesets")
        st.caption("Expand the categories below to make changes. Type your keywords cleanly with **one term per line**.")
        
        edited_profile = {}
        
        def list_to_textarea_string(lst):
            return "\n".join([str(x).strip() for x in lst if str(x).strip()])
            
        def textarea_string_to_list(txt):
            return [line.strip() for line in txt.split("\n") if line.strip()]

        with st.expander("✨ View/Edit Allowed Brand Variants & Misspellings", expanded=False):
            bv_raw_list = st.session_state.brand_profile.get("brand_variants", [])
            bv_text = st.text_area("Enter Brand Variants (One per line):", value=list_to_textarea_string(bv_raw_list), height=150, key="ta_bv")
            edited_profile["brand_variants"] = textarea_string_to_list(bv_text)

        with st.expander("🛡️ View/Edit Protected Core Offering Terms (Safety Shield)", expanded=False):
            prot_raw_list = st.session_state.brand_profile.get("protected_terms", [])
            prot_text = st.text_area("Enter Protected Core Terms (One per line):", value=list_to_textarea_string(prot_raw_list), height=150, key="ta_prot")
            edited_profile["protected_terms"] = textarea_string_to_list(prot_text)

        with st.expander("🚨 View/Edit Competitor Target Brand Names (Red Flags)", expanded=False):
            comp_raw_list = st.session_state.brand_profile.get("competitors", [])
            comp_text = st.text_area("Enter Competitor Brands (One per line):", value=list_to_textarea_string(comp_raw_list), height=150, key="ta_comp")
            edited_profile["competitors"] = textarea_string_to_list(comp_text)

        with st.expander("❌ View/Edit Clear Irrelevant Elements & Concepts", expanded=False):
            irr_raw_list = st.session_state.brand_profile.get("irrelevant_terms", [])
            irr_text = st.text_area("Enter Irrelevant Concepts (One per line):", value=list_to_textarea_string(irr_raw_list), height=150, key="ta_irr")
            edited_profile["irrelevant_terms"] = textarea_string_to_list(irr_text)

        with st.expander("🌐 View/Edit Allowed Target Languages & Regions", expanded=False):
            lang_raw_list = st.session_state.brand_profile.get("allowed_languages", ["English"])
            lang_text = st.text_area("Enter Target Languages (One per line):", value=list_to_textarea_string(lang_raw_list), height=100, key="ta_lang")
            edited_profile["allowed_languages"] = textarea_string_to_list(lang_text)
            
        st.markdown("---")
        
        if st.button("Confirm and Update Brand Knowledge Base", type="primary"):
            b_title = st.session_state.get("temp_brand_name", "Brand").strip()
            t_title = st.session_state.get("temp_campaign_type", "Search").strip()
            a_title = st.session_state.get("temp_ad_group_name", "AdGroup").strip()
            
            cache_key = f"{b_title} | {t_title} | {a_title}"
            save_profile_to_cache(cache_key, edited_profile)
            
            st.session_state.locked_rules = edited_profile
            st.session_state.cache_key = cache_key
            st.session_state.stage = 2
            st.success("Absolute truth established and updated in cache database. Moving to Stage 2...")
            st.rerun()

# =====================================================================
# STAGE 2: PRECISION MATRIX AUDIT (AI PROCESSING LAYER)
# =====================================================================
elif st.session_state.stage == 2:
    st.header("Stage 2: Precision Matrix Execution")
    st.subheader("Executing AI Negative Keyword Analysis")

    # Safety structural assertion checks
    if "brand_profile" not in st.session_state or not st.session_state.brand_profile:
        st.error("❌ Brand Profile baseline data is missing. Please return to Stage 1.")
        if st.button("⬅️ Back to Stage 1"):
            st.session_state.stage = 1
            st.rerun()
        st.stop()

    if "raw_search_terms" not in st.session_state or not st.session_state.raw_search_terms:
        st.error("❌ Search terms target data is missing. Please return to Stage 1.")
        if st.button("⬅️ Back to Stage 1"):
            st.session_state.stage = 1
            st.rerun()
        st.stop()

    search_terms = st.session_state.raw_search_terms
    total_input_count = len(search_terms)

    # Initialize Stage 2 localized tracking state variables if not present
    if "audit_results" not in st.session_state:
        st.session_state.audit_results = {}

    # Calculate real-time state values from active session state ledger
    processed_terms_set = set(st.session_state.audit_results.keys())
    relevant_list = [t for t, v in st.session_state.audit_results.items() if v["classification"] == "relevant"]
    irrelevant_list = [t for t, v in st.session_state.audit_results.items() if v["classification"] == "irrelevant"]
    review_list = [t for t, v in st.session_state.audit_results.items() if v["classification"] == "review"]
    
    # Track items missed by the API generation boundary
    current_loop_index = len(processed_terms_set)
    overlooked_list = [t for t in search_terms[:current_loop_index] if t not in processed_terms_set]

    # --- PROGRESS USER INTERFACE ---
    col1, col2 = st.columns([4, 1])
    with col1:
        st.info("💡 The app uses a fast, paced execution loop (50 terms per chunk) to maximize Gemini generation speeds and prevent server connection drops.")
    with col2:
        if st.button("🔄 Clear & Restart Audit", type="secondary"):
            st.session_state.audit_results = {}
            st.rerun()

    progress_bar = st.progress(len(processed_terms_set) / total_input_count if total_input_count > 0 else 0.0)
    counter_text = st.empty()

    # Dynamic Live Metric Board Layout
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Processed", f"{len(processed_terms_set)}")
    m2.metric("Relevant ✅", f"{len(relevant_list)}")
    m3.metric("Irrelevant ❌", f"{len(irrelevant_list)}")
    m4.metric("Review Queue 🔍", f"{len(review_list)}")
    m5.metric("Overlooked ⚠️", f"{len(overlooked_list)}")

    # Check if processing is complete
    if len(processed_terms_set) >= total_input_count:
        st.success("🎉 Precision Matrix Processing Complete!")
        
        if st.button("🚀 Proceed to Stage 3: Triage Desk", type="primary"):
            st.session_state.stage = 3
            st.rerun()
    else:
        # Action button to trigger processing execution
        if st.button("⚡ Start Precision Matrix Audit", type="primary"):
            from backend_stage2 import classify_terms_batch
            import time

            # --- CHUNK PROCESSING CONFIGURATION ---
            BATCH_SIZE = 50  # Small, lightweight chunk structure for maximum model velocity
            batch_count = 0  

            # --- CHUNK PROCESSING LOOP ---
            for i in range(0, total_input_count, BATCH_SIZE):
                batch = search_terms[i:i + BATCH_SIZE]
                
                # Check if this batch is already completely processed to allow resumption
                if all(t in st.session_state.audit_results for t in batch):
                    continue

                # API Quota Pacer: Every 12 fast requests, take a 45-second breath 
                # to reset Google's Requests-Per-Minute (RPM) wall safely.
                if batch_count > 0 and batch_count % 12 == 0:
                    for remaining in range(45, 0, -1):
                        counter_text.text(f"⏳ Rate-Limit Protection: Pausing for {remaining}s to refresh Google API limits...")
                        time.sleep(1)
                
                counter_text.text(f"Processing Precision Matrix Chunk: Terms {i} to {min(i + BATCH_SIZE, total_input_count)} of {total_input_count}...")
                
                # Call the rock-solid text-parsed backend batch classifier
                batch_results = classify_terms_batch(batch, st.session_state.brand_profile)
                batch_count += 1  
                
                # Safely write results into state ledger
                for res in batch_results:
                    st.session_state.audit_results[res["search_term"]] = {
                        "classification": res["classification"],
                        "confidence": res["confidence"],
                        "reason": res["reason"]
                    }
                
                # Recalculate runtime variables for live display update
                processed_terms_set = set(st.session_state.audit_results.keys())
                relevant_list = [t for t, v in st.session_state.audit_results.items() if v["classification"] == "relevant"]
                irrelevant_list = [t for t, v in st.session_state.audit_results.items() if v["classification"] == "irrelevant"]
                review_list = [t for t, v in st.session_state.audit_results.items() if v["classification"] == "review"]
                overlooked_list = [t for t in search_terms[:i + len(batch)] if t not in processed_terms_set]
                
                # Refresh progress metrics live
                progress_bar.progress(len(processed_terms_set) / total_input_count)
                m1.metric("Processed", f"{len(processed_terms_set)}")
                m2.metric("Relevant ✅", f"{len(relevant_list)}")
                m3.metric("Irrelevant ❌", f"{len(irrelevant_list)}")
                m4.metric("Review Queue 🔍", f"{len(review_list)}")
                m5.metric("Overlooked ⚠️", f"{len(overlooked_list)}")
                
                # Stabilizer step breath
                time.sleep(1)
            
            counter_text.text("Processing complete! Refreshing interface...")
            st.rerun()

# =====================================================================
# STAGE 3: TRIAGE DESK & EXPORT ROUTING
# =====================================================================
elif st.session_state.stage == 3:
# ==========================================
# 📊 OUTPUT SUMMARY & BATCH TRIAGE
# ==========================================
if st.session_state.get("audit_results") is not None:
    res_data = st.session_state.audit_results
    
    st.markdown("---")
    st.subheader("🛡️ Audit Summary Performance Data")
    
    # --- DYNAMIC HIGH-INTENSITY RED ALERT ENGINE ---
    overlooked_count = res_data["metrics"]["Potentially Overlooked Terms"]
    
    if overlooked_count > 0:
        if overlooked_count <= 10:
            st.error(
                f"🚨 **Critical Attention Required:** {overlooked_count} search term(s) bypassed direct automation rules "
                f"and were routed to the overlooked queue to prevent app suspension. Please expand the pipeline ledger "
                f"below and manually review these missed terms."
            )
        else:
            st.error(
                f"🔥 **Data Skew Warning:** {overlooked_count} search terms bypassed direct categorization. This volume "
                f"indicates your source data is likely skewed and current outputs should be taken with a pinch of salt. "
                f"For accurate system sorting results, please optimize your rulesets and run the search term audit again."
            )
    
    # 1. Full-Width Metrics Bar
    met_cols = st.columns(6)
    metrics_mapping = [
        ("Total Inputted Terms", "Total Inputted Terms"),
        ("Relevant Terms ✅", "Relevant Terms"),
        ("Irrelevant Terms ❌", "Irrelevant Terms"),
        ("Review Queue 🔍", "Review Queue Terms"),
        ("Potentially Overlooked ⚠️", "Potentially Overlooked Terms"),
        ("Extracted Roots Count 🪵", "Extracted Roots Count")
    ]
    
    for idx, (label, key) in enumerate(metrics_mapping):
        with met_cols[idx]:
            st.markdown(f'<div class="metric-bold-label">{label}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-bold-value">{res_data["metrics"][key]}</div>', unsafe_allow_html=True)
            
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Initialize triage engine states if missing
    from backend_stage3 import update_brand_profile_cache

    if "triage_list" not in st.session_state:
        st.session_state.triage_list = [item["Search Term"] for item in res_data["review"]] + [item["Search Term"] for item in res_data["overlooked"]]
    if "select_all_triage" not in st.session_state:
        st.session_state.select_all_triage = False
    if "cache_committed" not in st.session_state:
        st.session_state.cache_committed = False

    # 2. Split Screen Layout: 50/50 Division
    split_left, split_right = st.columns([1, 1])
    
    # --- LEFT SIDE: CLEAN TRIAGE CONTAINER ---
    with split_left:
        st.subheader("🔍 Review Queue Triage")
        st.caption("Select items using the checkboxes below and route them to their target database destination.")
        
        if st.session_state.triage_list:
            checked_count = 0
            for index, term in enumerate(st.session_state.triage_list):
                if st.session_state.get(f"triage_chk_row_{term}_{index}", False):
                    checked_count += 1
            
            total_items = len(st.session_state.triage_list)
            majority_selected = checked_count > (total_items / 2)
            toggle_label = "⬜ Deselect All" if majority_selected else "✅ Select All"
            
            act_col1, act_col2, act_col3 = st.columns(3)
            
            if act_col1.button(toggle_label, use_container_width=True):
                target_state = not majority_selected
                for index, term in enumerate(st.session_state.triage_list):
                    st.session_state[f"triage_chk_row_{term}_{index}"] = target_state
                st.rerun()
                
            trigger_move_relevant = act_col2.button("👍 Move to Relevant", use_container_width=True)
            trigger_move_irrelevant = act_col3.button("👎 Move to Irrelevant", use_container_width=True)
            
            selected_terms = []
            st.markdown("<br>", unsafe_allow_html=True)
            
            with st.container(height=350):
                for index, term in enumerate(st.session_state.triage_list):
                    row_cols = st.columns([1, 9])
                    is_selected = row_cols[0].checkbox(
                        " ", 
                        key=f"triage_chk_row_{term}_{index}",
                        label_visibility="collapsed"
                    )
                    row_cols[1].text(term)
                    if is_selected:
                        selected_terms.append(term)
                    
            # --- HIGH-SPEED SET-MAPPED TRIAGE ACTION DESK (FIXED SLOWDOWN) ---
            if trigger_move_relevant or trigger_move_irrelevant:
                if not selected_terms:
                    st.warning("⚠️ Please select items using the checkboxes or use the toggle button first.")
                else:
                    is_rel = trigger_move_relevant
                    
                    # Flatten arrays into instant O(1) memory hash-sets
                    existing_relevant = {r["Search Term"] for r in res_data["relevant"]}
                    existing_irrelevant = {i["Search Term"] for i in res_data["irrelevant"]}
                    existing_copy_paste = set(res_data["copy_paste_list"])
                    
                    new_relevant_entries = []
                    new_irrelevant_entries = []
                    new_notations = []
                    
                    if is_rel:
                        for t in selected_terms:
                            if t not in existing_relevant:
                                new_relevant_entries.append({"Search Term": t, "Confidence Score": 1.0, "Reasoning": "Human Triage Map"})
                        res_data["relevant"].extend(new_relevant_entries)
                    else:
                        for t in selected_terms:
                            if t not in existing_irrelevant:
                                new_irrelevant_entries.append({"Search Term": t, "Confidence Score": 1.0, "Reasoning": "Human Triage Map"})
                                notation = apply_ads_notation(t, is_exact=False)
                                if notation not in existing_copy_paste:
                                    new_notations.append(notation)
                                    existing_copy_paste.add(notation)
                                    
                        res_data["irrelevant"].extend(new_irrelevant_entries)
                        res_data["copy_paste_list"].extend(new_notations)
                    
                    # Evacuate selected terms instantly
                    triage_set = set(selected_terms)
                    for index, term in enumerate(st.session_state.triage_list):
                        if term in triage_set:
                            key_to_clear = f"triage_chk_row_{term}_{index}"
                            if key_to_clear in st.session_state:
                                del st.session_state[key_to_clear]
                                
                    st.session_state.triage_list = [t for t in st.session_state.triage_list if t not in triage_set]
                    res_data["review"] = [r for r in res_data["review"] if r["Search Term"] not in triage_set]
                    res_data["overlooked"] = [o for o in res_data["overlooked"] if o["Search Term"] not in triage_set]
                    
                    res_data["metrics"]["Review Queue Terms"] = len(res_data["review"])
                    res_data["metrics"]["Potentially Overlooked Terms"] = len(res_data["overlooked"])
                    res_data["metrics"]["Relevant Terms"] = len(res_data["relevant"])
                    res_data["metrics"]["Irrelevant Terms"] = len(res_data["irrelevant"])
                    
                    st.session_state.cache_committed = False
                    st.session_state.audit_results = res_data
                    st.success(f"Successfully routed {len(selected_terms)} terms internally!")
                    st.rerun()
        else:
            st.info("🎉 All items fully triaged inside this active configuration run.")

    # --- RIGHT SIDE: EXACT STYLE COPY-PASTE FORMATTED OUTPUT & OVERLOOKED ---
    with split_right:
        st.subheader("🎯 Optimization Output: Google Ads Copy-Paste Match List")
        st.caption("Copy this target data string completely straight onto campaign parameters negative target keywords list inputs.")
        text_block = "\n".join(res_data["copy_paste_list"])
        st.text_area("Ready Matrix List Output Data Box", value=text_block, height=350, label_visibility="visible")
        
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("⚠️ Review Potentially Overlooked Terms Pipeline Ledger", expanded=False):
            overlooked_items = [o["Search Term"] for o in res_data.get("overlooked", [])]
            if overlooked_items:
                for item in overlooked_items:
                    st.text(f"• {item}")
            else:
                st.info("No bypass terms detected tracking inside current session threshold parameters.")

    # =========================================================================
    # 3. FULL-WIDTH WORKSPACE CONTROLS FOOTER WITH BRANDING INJECTED STYLES
    # =========================================================================
    st.subheader("⚙️ Global Workspace Controls")
    
    st.markdown("""
        <style>
            div[data-testid="stExpander"] div[role="region"] { padding: 24px 20px !important; }
            div[data-testid="stForm"] { padding: 20px !important; }
            .stTextArea textarea { padding: 14px !important; }
            div.stButton > button:first-child { padding: 12px 20px !important; font-weight: 600 !important; }
        </style>
    """, unsafe_allow_html=True)

    footer_container = st.container()
    with footer_container:
        foot_col1, foot_col2, foot_col3 = st.columns(3)
        
        # Control Button A: Download Workbook Ledger
        with foot_col1:
            st.markdown("""
                <style>
                    div[data-testid="stBlock"] div[data-testid="stHorizontalBlock"] > div:nth-child(1) button {
                        background-color: #2E7D32 !important; color: white !important; border: 1px solid #1B5E20 !important;
                    }
                    div[data-testid="stBlock"] div[data-testid="stHorizontalBlock"] > div:nth-child(1) button:hover {
                        background-color: #1B5E20 !important;
                    }
                </style>
            """, unsafe_allow_html=True)
            
            payload = {
                "Metrics Data": [{"Metric Name": k, "Value": v} for k, v in res_data["metrics"].items()],
                "Relevant Search Terms": res_data["relevant"],
                "Irrelevant Search Terms": res_data["irrelevant"],
                "Review Queue": res_data["review"],
                "Potentially Overlooked": res_data["overlooked"],
                "Root Negatives": res_data["roots"]
            }
            
            csv_stream = push_to_google_sheets(st.session_state.cache_key, payload)
            if csv_stream is not None:
                st.download_button(
                    label="🚀 Download Workbook Ledger (.csv)",
                    data=csv_stream,
                    file_name=f"Negative_Optimization_Ledger_{st.session_state.get('cache_key', 'export').replace(' | ', '_')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            else:
                st.error("Matrix stream build failed.")

        # Control Button B: Cache Audit Into Brand Knowledge
        with foot_col2:
            st.markdown("""
                <style>
                    div[data-testid="stBlock"] div[data-testid="stHorizontalBlock"] > div:nth-child(2) button {
                        background-color: #C62828 !important; color: white !important; border: 1px solid #B71C1C !important;
                    }
                    div[data-testid="stBlock"] div[data-testid="stHorizontalBlock"] > div:nth-child(2) button:hover {
                        background-color: #B71C1C !important;
                    }
                    div[data-testid="stBlock"] div[data-testid="stHorizontalBlock"] > div:nth-child(2) button:disabled {
                        background-color: #E0E0E0 !important; color: #9E9E9E !important; border: 1px solid #BDBDBD !important;
                    }
                </style>
            """, unsafe_allow_html=True)
            
            cache_btn_label = "✅ Audit Knowledge Cached" if st.session_state.cache_committed else "💾 Cache Audit into Brand Knowledge"
            
            if st.button(cache_btn_label, use_container_width=True, disabled=st.session_state.cache_committed):
                with st.spinner("Committing verified session definitions directly to cloud master ledger cache..."):
                    raw_cache_key = st.session_state.cache_key
                    profile_sig = raw_cache_key.split(" | ")[0].strip() if " | " in raw_cache_key else raw_cache_key
                    
                    rel_payload = [r["Search Term"] for r in res_data["relevant"]]
                    irr_payload = [i["Search Term"] for i in res_data["irrelevant"]]
                    
                    success = update_brand_profile_cache(
                        cache_key=profile_sig,
                        new_relevant_terms=rel_payload,
                        new_irrelevant_terms=irr_payload
                    )
                    if success:
                        st.session_state.cache_committed = True
                        st.success("Cloud database successfully trained with current session intelligence metrics parameters!")
                        st.rerun()
                    else:
                        st.error("Pipeline connectivity error tracking database parameters back into cloud rows layer.")

        # Control Button C: Start Fresh Engine Matrix Audit Run
        with foot_col3:
            st.markdown("""
                <style>
                    div[data-testid="stBlock"] div[data-testid="stHorizontalBlock"] > div:nth-child(3) button {
                        background-color: #1565C0 !important; color: white !important; border: 1px solid #0D47A1 !important;
                    }
                    div[data-testid="stBlock"] div[data-testid="stHorizontalBlock"] > div:nth-child(3) button:hover {
                        background-color: #0D47A1 !important;
                    }
                </style>
            """, unsafe_allow_html=True)
            if st.button("🔄 Start New Audit", use_container_width=True):
                for index, term in enumerate(st.session_state.get("triage_list", [])):
                    key_to_clear = f"triage_chk_row_{term}_{index}"
                    if key_to_clear in st.session_state:
                        del st.session_state[key_to_clear]
                
                if "triage_list" in st.session_state:
                    del st.session_state.triage_list
                if "audit_results" in st.session_state:
                    del st.session_state.audit_results
                if "cache_committed" in st.session_state:
                    del st.session_state.cache_committed
                
                st.session_state.stage = 1
                st.rerun()
