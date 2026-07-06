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
    
    # 1. Fetch raw cache entries from sheet rows
    cache_options = get_cached_profiles()
    
    # 2. Parse out isolated, unique portfolio brand tokens
    unique_brands = set()
    for option in cache_options:
        if option != "Create New":
            parts = option.split(" | ")
            unique_brands.add(parts[0].strip())
            
    brand_list = ["-Please Select-", "Create New"] + sorted(list(unique_brands), key=str.lower)
    
    # --- CASCADING INTERFACE BLOCKS ---
    col_b1, col_b2 = st.columns(2)
    
    with col_b1:
        selected_brand_tier = st.selectbox("🏢 Select Brand Portfolio", options=brand_list, index=0)
        
    selected_cache = "Create New"
    
    with col_b2:
        if selected_brand_tier not in ["-Please Select-", "Create New"]:
            # Extract sub-components matching chosen brand portfolio
            matching_workspaces = []
            for option in cache_options:
                if option.startswith(f"{selected_brand_tier} | "):
                    workspace_suffix = option.replace(f"{selected_brand_tier} | ", "").strip()
                    matching_workspaces.append(workspace_suffix)
            
            # Auto-inject safety fallback to force active choice selection
            workspace_options = ["-Please Select-"] + sorted(matching_workspaces, key=str.lower)
            selected_workspace_tier = st.selectbox("🎯 Select Active Campaign / Ad Group Workspace", options=workspace_options, index=0)
            
            if selected_workspace_tier != "-Please Select-":
                selected_cache = f"{selected_brand_tier} | {selected_workspace_tier}"
            else:
                selected_cache = "-Please Select-"
        else:
            st.selectbox("🎯 Select Active Campaign Workspace", options=["N/A - Choose Portfolio Entry"], disabled=True)
    
    st.markdown("---")
    
    # --- SCENARIO A: BLOCKED ON SELECT ---
    if selected_cache == "-Please Select-" or selected_brand_tier == "-Please Select-":
        st.info("👋 Please select a valid Brand Portfolio and Ad Group Workspace to load parameters, or choose 'Create New'.")
        st.session_state.brand_profile = None
        st.session_state.locked_rules = None

    # --- SCENARIO B: ACTIVE LOAD FROM CACHE ---
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
        
        # Outputs rendered exclusively as locked selectboxes
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

    # --- SCENARIO C: FRESH PROFILE BUILDER ---
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
        
        # Helper string conversion functions to map line-breaks smoothly to python arrays
        def list_to_textarea_string(lst):
            return "\n".join([str(x).strip() for x in lst if str(x).strip()])
            
        def textarea_string_to_list(txt):
            return [line.strip() for line in txt.split("\n") if line.strip()]

        # Dropdown Box 1: Brand Variants
        with st.expander("✨ View/Edit Allowed Brand Variants & Misspellings", expanded=False):
            bv_raw_list = st.session_state.brand_profile.get("brand_variants", [])
            bv_text = st.text_area("Enter Brand Variants (One per line):", value=list_to_textarea_string(bv_raw_list), height=150, key="ta_bv")
            edited_profile["brand_variants"] = textarea_string_to_list(bv_text)

        # Dropdown Box 2: Protected Core Terms
        with st.expander("🛡️ View/Edit Protected Core Offering Terms (Safety Shield)", expanded=False):
            prot_raw_list = st.session_state.brand_profile.get("protected_terms", [])
            prot_text = st.text_area("Enter Protected Core Terms (One per line):", value=list_to_textarea_string(prot_raw_list), height=150, key="ta_prot")
            edited_profile["protected_terms"] = textarea_string_to_list(prot_text)

        # Dropdown Box 3: Competitors
        with st.expander("🚨 View/Edit Competitor Target Brand Names (Red Flags)", expanded=False):
            comp_raw_list = st.session_state.brand_profile.get("competitors", [])
            comp_text = st.text_area("Enter Competitor Brands (One per line):", value=list_to_textarea_string(comp_raw_list), height=150, key="ta_comp")
            edited_profile["competitors"] = textarea_string_to_list(comp_text)

        # Dropdown Box 4: Irrelevant Concepts
        with st.expander("❌ View/Edit Clear Irrelevant Elements & Concepts", expanded=False):
            irr_raw_list = st.session_state.brand_profile.get("irrelevant_terms", [])
            irr_text = st.text_area("Enter Irrelevant Concepts (One per line):", value=list_to_textarea_string(irr_raw_list), height=150, key="ta_irr")
            edited_profile["irrelevant_terms"] = textarea_string_to_list(irr_text)

        # Dropdown Box 5: Target Languages
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

# ==========================================
# 📊 STAGE 2: SEARCH TERMS AUDIT ENGINE
# ==========================================
elif st.session_state.stage == 2:
    st.header(f"Stage 2: Audit Engine — Workspace: {st.session_state.cache_key}")
    
    uploaded_file = st.file_uploader("Upload Search Term Export (CSV Format)", type=["csv"], disabled=st.session_state.audit_running)
    
    # Optimized batch structure for balanced API economics and performance
    BATCH_SIZE = 100
    
    if uploaded_file:
        try:
            uploaded_file.seek(0)
            df_preview = pd.read_csv(uploaded_file)
            term_col_preview = next((c for c in df_preview.columns if "search term" in c.lower() or "query" in c.lower()), None)
            
            if term_col_preview:
                raw_count = len(df_preview[term_col_preview].dropna().drop_duplicates())
                num_batches = (raw_count + BATCH_SIZE - 1) // BATCH_SIZE
                
                paid_seconds = max(int(num_batches * 2.0), 2)
                paid_display = f"{paid_seconds // 60} min {paid_seconds % 60} sec" if paid_seconds >= 60 else f"{paid_seconds} seconds"
                
                st.warning(
                    f"📊 **Dataset Loaded:** {raw_count} unique search terms detected ({num_batches} loops of {BATCH_SIZE} rows).\n\n"
                    f"⏱️ **Precision Tier Speed Matrix:** Estimated completion in **{paid_display}**."
                )
            else:
                st.error("🛑 **Error Code: E005 - System Operational Failure**\n\nMissing Required Column Mapping. File must contain a column titled either 'Search Term' or 'Query'.")
        except Exception as e:
            st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nFile read breakdown: {str(e)}")

    button_text = "Processing Audit Engine Matrix..." if st.session_state.audit_running else "Launch Search Terms Audit"
    
    if st.button(button_text, type="secondary", use_container_width=True, disabled=st.session_state.audit_running):
        if not uploaded_file:
            st.error("🛑 **Error Code: E002 - Missing File Stream**\n\nThe Search Term Ledger dataset CSV upload path is missing.")
        else:
            st.session_state.audit_running = True
            st.rerun()

    if st.session_state.audit_running:
        with st.spinner("⏳ Running Search Terms Audit Engine... Please do not close or refresh this tab."):
            try:
                uploaded_file.seek(0)
                df_input = pd.read_csv(uploaded_file)
                term_col = next((c for c in df_input.columns if "search term" in c.lower() or "query" in c.lower()), None)
                search_terms = df_input[term_col].dropna().drop_duplicates().tolist()
                total_input_count = len(search_terms)
                
                progress_bar = st.progress(0)
                counter_text = st.empty()
                
                metric_slots = st.columns(5)
                m1, m2, m3, m4, m5 = (
                    metric_slots[0].empty(), metric_slots[1].empty(), 
                    metric_slots[2].empty(), metric_slots[3].empty(), metric_slots[4].empty()
                )
                
                relevant_list, irrelevant_list, review_list, overlooked_list = [], [], [], []
                processed_terms_set = set()
                
                # --- CHUNK PROCESSING LOOP ---
                for i in range(0, total_input_count, BATCH_SIZE):
                    batch = search_terms[i:i + BATCH_SIZE]
                    counter_text.text(f"Processing Precision Matrix Chunk: Terms {i} to {min(i + BATCH_SIZE, total_input_count)} of {total_input_count}...")
                    
                    api_payload_batch = []
                    for term in batch:
                        if is_foreign_script(term):
                            irrelevant_list.append({
                                "Search Term": term, "Confidence Score": 1.00,
                                "Reasoning": "Automated Guardrail: Detected foreign non-Latin alphabet character."
                            })
                            processed_terms_set.add(term)
                        else:
                            api_payload_batch.append(term)

                    if api_payload_batch:
                        try:
                            batch_results = classify_terms_batch(api_payload_batch, st.session_state.locked_rules)
                            for res in batch_results:
                                term_string = res.get("search_term", "")
                                if term_string:
                                    processed_terms_set.add(term_string)
                                    row_data = {
                                        "Search Term": term_string,
                                        "Confidence Score": res.get("confidence", 1.00),
                                        "Reasoning": res.get("reason", "Classified successfully")
                                    }
                                    if res.get("classification") == "relevant":
                                        relevant_list.append(row_data)
                                    elif res.get("classification") == "irrelevant":
                                        irrelevant_list.append(row_data)
                                    else:
                                        review_list.append(row_data)
                        except Exception as batch_err:
                            for term in api_payload_batch:
                                if term not in processed_terms_set:
                                    overlooked_list.append({
                                        "Search Term": term, "Confidence Score": 0.00,
                                        "Reasoning": f"Batch exception caught: {str(batch_err)}"
                                    })
                                    processed_terms_set.add(term)
                    
                    percent_complete = int((min(i + BATCH_SIZE, total_input_count) / total_input_count) * 100)
                    progress_bar.progress(percent_complete)
                    
                    m1.metric("Processed", f"{len(processed_terms_set)}")
                    m2.metric("Relevant ✅", f"{len(relevant_list)}")
                    m3.metric("Irrelevant ❌", f"{len(irrelevant_list)}")
                    m4.metric("Review Queue 🔍", f"{len(review_list)}")
                    m5.metric("Overlooked ⚠️", f"{len(overlooked_list)}")

                for term in search_terms:
                    if term not in processed_terms_set:
                        overlooked_list.append({
                            "Search Term": term, "Confidence Score": 0.00, "Reasoning": "System reconciliation catch alignment"
                        })

                irr_phrases = [r["Search Term"] for r in irrelevant_list]
                saved_phrases = [r["Search Term"] for r in relevant_list] + [r["Search Term"] for r in review_list] + [r["Search Term"] for r in overlooked_list]
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
                        
                    if bool(phrase_words & protected_words):
                        final_negatives_output.append(apply_ads_notation(phrase, is_exact=False))
                    elif not (phrase_words & active_root_words):
                        final_negatives_output.append(apply_ads_notation(phrase, is_exact=False))
                            
                final_negatives_output = list(set(final_negatives_output))
                
                st.session_state.audit_results = {
                    "metrics": {
                        "Total Inputted Terms": total_input_count,
                        "Relevant Terms": len(relevant_list),
                        "Irrelevant Terms": len(irrelevant_list),
                        "Review Queue Terms": len(review_list),
                        "Potentially Overlooked Terms": len(overlooked_list),
                        "Extracted Roots Count": len(root_negatives_payload)
                    },
                    "relevant": relevant_list, "irrelevant": irrelevant_list,
                    "review": review_list, "overlooked": overlooked_list,
                    "roots": root_negatives_payload, "copy_paste_list": final_negatives_output
                }
                st.session_state.audit_running = False
                st.success("Analysis matrix generated.")
                st.rerun()
                
            except Exception as main_err:
                st.session_state.audit_running = False
                st.error(f"🔧 **Error Code: E005** - Computation failed: {str(main_err)}")

# ==========================================
# 📊 OUTPUT SUMMARY & BATCH TRIAGE
# ==========================================
if st.session_state.audit_results:
    res_data = st.session_state.audit_results
    
    st.markdown("---")
    st.subheader("🛡️ Audit Summary Performance Data")
    
    if res_data["metrics"]["Potentially Overlooked Terms"] > 0:
        st.warning("⚠️ **Notice:** Some search terms bypassed direct categorization and were routed to the overlooked queue to prevent app suspension.")
    
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
    
    # Initialize the triage engine state arrays if missing
    from backend_stage3 import update_brand_profile_cache

    if "triage_list" not in st.session_state:
        st.session_state.triage_list = [item["Search Term"] for item in res_data["review"]] + [item["Search Term"] for item in res_data["overlooked"]]
    if "select_all_triage" not in st.session_state:
        st.session_state.select_all_triage = False

    # 2. Split Screen Layout: 50/50 Division
    split_left, split_right = st.columns([1, 1])
    
# --- LEFT SIDE: DROPDOWN TABLE WITH ACTION CONTROLS ---
    with split_left:
        with st.expander("🔍 Review & Triage Queue Ledger Table", expanded=True):
            if st.session_state.triage_list:
                
                # Action Control Buttons Array Header
                act_col1, act_col2, act_col3 = st.columns(3)
                
                # Toggle Select All State Variable on click
                if act_col1.button("✅ Select All", use_container_width=True):
                    st.session_state.select_all_triage = not st.session_state.select_all_triage
                    st.rerun()
                    
                trigger_move_relevant = act_col2.button("👍 Move to Relevant", use_container_width=True)
                trigger_move_irrelevant = act_col3.button("👎 Move to Irrelevant", use_container_width=True)
                
                selected_terms = []
                st.markdown("<br>", unsafe_allow_html=True)
                
                # Table Grid Header Fix (Stays pinned at the top)
                hdr_cols = st.columns([0.8, 5.2])
                hdr_cols[0].markdown("**Select**")
                hdr_cols[1].markdown("**Search Query String**")
                st.markdown("---")
                
                # --- EMBEDDED SCROLLABLE VIEWPORT CONTAINER ---
                # Fixed at 350px height to match your output text box cleanly
                st.markdown('<div style="max-height: 350px; overflow-y: auto; padding-right: 10px;">', unsafe_allow_html=True)
                
                for index, term in enumerate(st.session_state.triage_list):
                    row_cols = st.columns([0.8, 5.2])
                    
                    # Generate checkboxes with stable default states
                    is_selected = row_cols[0].checkbox(
                        " ", 
                        value=st.session_state.select_all_triage, 
                        key=f"triage_chk_row_{term}_{index}"
                    )
                    row_cols[1].text(term)
                    
                    if is_selected:
                        selected_terms.append(term)
                        
                st.markdown('</div>', unsafe_allow_html=True) # Close Scroll Container
                # ----------------------------------------------
                        
                # Route Actions Processing Block
                if trigger_move_relevant or trigger_move_irrelevant:
                    if not selected_terms:
                        st.warning("⚠️ Please select items using the checkboxes or use 'Select All' first.")
                    else:
                        is_rel = trigger_move_relevant
                        
                        if is_rel:
                            for t in selected_terms:
                                if not any(r["Search Term"] == t for r in res_data["relevant"]):
                                    res_data["relevant"].append({"Search Term": t, "Confidence Score": 1.0, "Reasoning": "Human Triage Map"})
                        else:
                            for t in selected_terms:
                                if not any(r["Search Term"] == t for r in res_data["irrelevant"]):
                                    res_data["irrelevant"].append({"Search Term": t, "Confidence Score": 1.0, "Reasoning": "Human Triage Map"})
                                    notation = apply_ads_notation(t, is_exact=False)
                                    if notation not in res_data["copy_paste_list"]:
                                        res_data["copy_paste_list"].append(notation)
                        
                        # Strip routed records from view
                        st.session_state.triage_list = [t for t in st.session_state.triage_list if t not in selected_terms]
                        res_data["review"] = [r for r in res_data["review"] if r["Search Term"] not in selected_terms]
                        res_data["overlooked"] = [o for o in res_data["overlooked"] if o["Search Term"] not in selected_terms]
                        
                        # Recalculate metrics counter values
                        res_data["metrics"]["Review Queue Terms"] = len(res_data["review"])
                        res_data["metrics"]["Potentially Overlooked Terms"] = len(res_data["overlooked"])
                        res_data["metrics"]["Relevant Terms"] = len(res_data["relevant"])
                        res_data["metrics"]["Irrelevant Terms"] = len(res_data["irrelevant"])
                        
                        st.session_state.audit_results = res_data
                        st.session_state.select_all_triage = False  # Reset selection state flag safely
                        st.success(f"Successfully routed {len(selected_terms)} terms internally!")
                        st.rerun()
            else:
                st.info("🎉 All items fully triaged inside this active configuration run.")

    # --- RIGHT SIDE: EXACT STYLE COPY-PASTE FORMATTED OUTPUT ---
    with split_right:
        st.subheader("🎯 Optimization Output: Google Ads Copy-Paste Match List")
        st.caption("Copy this target data string completely straight onto campaign parameters negative target keywords list inputs.")
        text_block = "\n".join(res_data["copy_paste_list"])
        st.text_area("Ready Matrix List Output Data Box", value=text_block, height=350)

    st.markdown("<br><hr><br>", unsafe_allow_html=True)

    # 3. Full-Width Workspace Footer Controls Layout
    st.subheader("⚙️ Global Workspace Controls")
    foot_col1, foot_col2, foot_col3 = st.columns(3)
    
    # Control Button A: Download Workbook Ledger
    with foot_col1:
        if st.button("🚀 Download Workbook Ledger", use_container_width=True):
            payload = {
                "Metrics Data": [{"Metric Name": k, "Value": v} for k, v in res_data["metrics"].items()],
                "Relevant Search Terms": res_data["relevant"],
                "Irrelevant Search Terms": res_data["irrelevant"],
                "Review Queue": res_data["review"],
                "Potentially Overlooked": res_data["overlooked"],
                "Root Negatives": res_data["roots"]
            }
            with st.spinner("Provisioning real-time Google Sheet asset structure..."):
                try:
                    direct_url = push_to_google_sheets(st.session_state.cache_key, payload)
                    st.success("Google Sheets Asset generated successfully!")
                    st.markdown(f"[🔗 Click to Open Your Google Sheet Workspace]({direct_url})")
                except Exception as e:
                    st.error(f"🔧 **Error Code: E005** - Cloud ledger pipeline interrupted: {str(e)}")

    # Control Button B: Cache Audit Into Brand Knowledge Database Row Range
    with foot_col2:
        if st.button("💾 Cache Audit into Brand Knowledge", type="primary", use_container_width=True):
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
                    st.success("Cloud database successfully trained with current session intelligence metrics parameters!")
                else:
                    st.error("Pipeline connectivity error tracking database parameters back into cloud rows layer.")

    # Control Button C: Start Fresh Engine Matrix Audit Run
    with foot_col3:
        if st.button("🔄 Start New Audit", use_container_width=True):
            if "triage_list" in st.session_state:
                del st.session_state.triage_list
            if "select_all_triage" in st.session_state:
                del st.session_state.select_all_triage
            st.session_state.stage = 1
            st.session_state.brand_profile = None
            st.session_state.locked_rules = None
            st.session_state.audit_results = None
            st.rerun()
