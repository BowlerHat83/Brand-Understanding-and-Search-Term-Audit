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
from backend_stage1 import run_brand_audit, route_bulk_keywords
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

@st.cache_data(ttl=60)
def get_cached_profiles():
    """Pulls all available brand profile names from the Google Sheet rows. Cached for 60 seconds."""
    try:
        gc = get_gspread_client()
        sheet = gc.open_by_key(st.secrets["CACHE_SPREADSHEET_ID"]).sheet1
        records = sheet.get_all_records()
        
        profile_names = [row["Profile Name"] for row in records if row.get("Profile Name")]
        return ["-Create New-"] + sorted(profile_names, key=str.lower)
    except Exception:
        return ["-Create New-"]

@st.cache_data(ttl=60)
def load_cached_profile(profile_name):
    """Finds the matching row, safely handling human-edited text formatting. Cached for 60 seconds."""
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
    
    # 1. Fetch raw cache entries from sheet rows (Leveraging Cache Layer)
    cache_options = get_cached_profiles()
    
    # 2. Parse out isolated, unique portfolio brand tokens cleanly without matching anchor strings
    unique_brands = set()
    for option in cache_options:
        if option not in ["-Create New-", "Create New"]:
            parts = option.split(" | ")
            unique_brands.add(parts[0].strip())
            
    brand_list = ["-Create New-"] + sorted(list(unique_brands), key=str.lower)
    
    # --- CASCADING INTERFACE BLOCKS ---
    col_b1, col_b2 = st.columns(2)
    
    with col_b1:
        selected_brand_tier = st.selectbox("🏢 Select Brand Portfolio", options=brand_list, index=0)
        
    selected_cache = "-Create New-"
    
    with col_b2:
        if selected_brand_tier != "-Create New-":
            # Extract sub-components matching chosen brand portfolio
            matching_workspaces = []
            for option in cache_options:
                if option.startswith(f"{selected_brand_tier} | "):
                    workspace_suffix = option.replace(f"{selected_brand_tier} | ", "").strip()
                    matching_workspaces.append(workspace_suffix)
            
            # Inject a mandatory "Please Select" anchor option
            workspace_options = ["-Please Select-"] + sorted(matching_workspaces, key=str.lower)
            
            selected_workspace_tier = st.selectbox(
                "🎯 Select Active Campaign / Ad Group Workspace", 
                options=workspace_options,
                index=0
            )
            
            if selected_workspace_tier and selected_workspace_tier != "-Please Select-":
                selected_cache = f"{selected_brand_tier} | {selected_workspace_tier}"
            else:
                selected_cache = "-Please Select-"
        else:
            st.selectbox("🎯 Select Active Campaign Workspace", options=["N/A - Creating New Brand Profile"], disabled=True)
    
    st.markdown("---")
    
    if selected_cache == "-Please Select-":
        st.info("ℹ️ Please select a specific Campaign / Ad Group Workspace from the dropdown menu above to load its profile parameters.")
        st.session_state.brand_profile = None
        st.session_state.locked_rules = None

    elif selected_cache != "-Create New-":
        if st.session_state.brand_profile is None or st.session_state.get('cache_key') != selected_cache:
            try:
                st.session_state.brand_profile = load_cached_profile(selected_cache)
                
                cache_parts = selected_cache.split(" | ")
                if len(cache_parts) == 3:
                    st.session_state.temp_brand_name = cache_parts[0]
                    st.session_state.temp_campaign_type = cache_parts[1]
                    st.session_state.temp_ad_group_name = cache_parts[2]
                else:
                    st.session_state.temp_brand_name = cache_parts[0]
                    st.session_state.temp_campaign_type = "Search"
                    st.session_state.temp_ad_group_name = cache_parts[1] if len(cache_parts) > 1 else ""
                    
                st.session_state.locked_rules = st.session_state.brand_profile
                st.session_state.cache_key = selected_cache
            except Exception as e:
                st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nFailed loading profile asset framework configuration. Details: {str(e)}")
                
        st.success(f"📋 Loaded configuration workspace layout baseline: **{selected_cache}**")
        
    else:
        if st.session_state.get('last_selected_cache') and st.session_state.get('last_selected_cache') not in ["-Create New-", "-Please Select-"]:
            st.session_state.brand_profile = None
            st.session_state.locked_rules = None
            
        row1_left, row1_right = st.columns(2)
        with row1_left:
            brand_name = st.text_input("Brand Name", value="")
        with row1_right:
            campaign_type = st.selectbox("Campaign Type", options=["-Please Select-", "Search", "PMax", "Display", "Shopping"])
            
        row2_left, row2_right = st.columns(2)
        with row2_left:
            ad_group_name = st.text_input("Ad Group Name", value="", placeholder="e.g., Competitor_Conversions_USA")
        with row2_right:
            core_offering = st.text_input("Core Offering of the Ad Group", value="", placeholder="What is this ad group selling? (Used for AI Context)")
            
        landing_pages = st.text_area(
            "Target Landing Page Links & Context (One link per line)", 
            placeholder="https://client.com/pricing\nhttps://client.com/remarketing-resource",
            height=120
        )
        
        if st.button("Launch Brand Understanding Audit"):
            if not brand_name or campaign_type == "-Please Select-" or not ad_group_name or not core_offering or not landing_pages:
                st.error("🛑 **Error Code: E001 - Missing Input Parameters**\n\nOne or more required input fields were left blank or unselected.")
            else:
                progress_bar = st.progress(0)
                st.empty()
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
                    err_str = str(e).lower()
                    if "429" in err_str or "quota" in err_str:
                        st.error("🛑 **Error Code: E003 - API Quota Exhausted**\n\nThe API speed limit was hit. Please pause for 60 seconds.")
                    elif "gemini" in err_str:
                        st.error("📡 **Error Code: E004 - Cloud Connection Dropped**\n\nThe connection to the Google Cloud AI loop was dropped mid-process. Please Try Again in a Few Minutes")
                    else:
                        st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nAn unexpected backend processing anomaly occurred. Details: {str(e)}")

    st.session_state.last_selected_cache = selected_cache

    if st.session_state.brand_profile:
        st.markdown("### 📝 Refine Brand Understanding Rulesets")
        st.caption("Expand the options below to add custom items, clear rows, or correct terms before cementing absolute rules.")
        
        edited_profile = {}
        
        # Row 1: Brand & Protected Core wrapped in toggles
        row1_col1, row1_col2 = st.columns(2)
        with row1_col1:
            with st.expander("✨ View/Edit Allowed Brand Variants & Misspellings", expanded=False):
                df_bv = pd.DataFrame(st.session_state.brand_profile.get("brand_variants", []), columns=["Brand Variants"])
                ed_bv = st.data_editor(df_bv, num_rows="dynamic", use_container_width=True, key="editor_bv")
                edited_profile["brand_variants"] = ed_bv["Brand Variants"].dropna().tolist()
            
        with row1_col2:
            with st.expander("🛡️ View/Edit Protected Core Offering Terms (Safety Shield)", expanded=False):
                df_prot = pd.DataFrame(st.session_state.brand_profile.get("protected_terms", []), columns=["Protected Core Terms"])
                ed_prot = st.data_editor(df_prot, num_rows="dynamic", use_container_width=True, key="editor_prot")
                edited_profile["protected_terms"] = ed_prot["Protected Core Terms"].dropna().tolist()
            
        # Row 2: Competitors & Irrelevant Concepts wrapped in toggles
        row2_col1, row2_col2 = st.columns(2)
        with row2_col1:
            with st.expander("🚨 View/Edit Competitor Target Brand Names (Red Flags)", expanded=False):
                df_comp = pd.DataFrame(st.session_state.brand_profile.get("competitors", []), columns=["Competitor Brands"])
                ed_comp = st.data_editor(df_comp, num_rows="dynamic", use_container_width=True, key="editor_comp")
                edited_profile["competitors"] = ed_comp["Competitor Brands"].dropna().tolist()
        with row2_col2:
            with st.expander("❌ View/Edit Clear Irrelevant Elements & Concepts", expanded=False):
                df_irr = pd.DataFrame(st.session_state.brand_profile.get("irrelevant_terms", []), columns=["Irrelevant Concepts"])
                ed_irr = st.data_editor(df_irr, num_rows="dynamic", use_container_width=True, key="editor_irr")
                edited_profile["irrelevant_terms"] = ed_irr["Irrelevant Concepts"].dropna().tolist()
            

        # 🌐 Row 3: 5th Box - Allowed Languages Matrix wrapped in toggle
        with st.expander("🌐 View/Edit Allowed Target Languages & Regions", expanded=False):
            default_languages = st.session_state.brand_profile.get("allowed_languages", ["English"])
            df_lang = pd.DataFrame(default_languages, columns=["Target Languages"])
            ed_lang = st.data_editor(df_lang, num_rows="dynamic", use_container_width=False, width=400, key="editor_lang")
            edited_profile["allowed_languages"] = ed_lang["Target Languages"].dropna().tolist()
            
        # ==========================================
        # 📥 NEW: BULK KNOWLEDGE ROUTER PLAYGROUND
        # ==========================================
        st.markdown("---")
        st.subheader("💡 Trial: Bulk Knowledge Router Playground")
        st.caption("Ignore for Now. Potentially a future feature.")
        
        bulk_input = st.text_area(
            "Paste bulk terms here (One phrase per line):",
            height=130,
            placeholder="free software\ncheap tool\n[competitor name xyz]\nfrançais\nmanual download pdf"
        )
        
        if st.button("⚡ Automatically Organize & Route Keywords", use_container_width=True):
            if not bulk_input.strip():
                st.warning("Please paste some bulk text lines to organize first.")
            else:
                with st.spinner("Analyzing root contexts and routing keyword matrix..."):
                    try:
                        # Map current state values to pull manual edits out of text inputs
                        current_ctx = {
                            "brand_variants": edited_profile.get("brand_variants", []),
                            "competitors": edited_profile.get("competitors", []),
                            "protected_terms": edited_profile.get("protected_terms", []),
                            "irrelevant_terms": edited_profile.get("irrelevant_terms", []),
                            "allowed_languages": edited_profile.get("allowed_languages", ["English"])
                        }
                        
                        # Call secondary routing call
                        routed_output = route_bulk_keywords(
                            bulk_text=bulk_input, 
                            current_profile=current_ctx,
                            target_language=", ".join(current_ctx["allowed_languages"])
                        )
                        
                        # Merge output and push to system state variables
                        for key in current_ctx:
                            # Re-map legacy key name variance checks safely
                            api_key_name = "target_languages" if key == "allowed_languages" else key
                            current_ctx[key].extend(routed_output.get(api_key_name, []))
                            current_ctx[key] = list(set(current_ctx[key])) # Deduplicate
                            
                        st.session_state.brand_profile = current_ctx
                        st.success("All historical phrases routed perfectly! Check the edited expanding panels above.")
                        st.rerun()
                    except Exception as route_err:
                        st.error(f"Routing Module Failure: {str(route_err)}")
                        
        st.markdown("---")
        
        if st.button("Confirm and Update Brand Knowledge Base", type="primary"):
            b_title = st.session_state.get("temp_brand_name", "Brand").strip()
            t_title = st.session_state.get("temp_campaign_type", "Search").strip()
            a_title = st.session_state.get("temp_ad_group_name", "AdGroup").strip()
            
            cache_key = f"{b_title} | {t_title} | {a_title}"
            save_profile_to_cache(cache_key, edited_profile)
            
            # Clear memory cache so the drop-down elements refresh cleanly immediately on next load
            st.cache_data.clear()
            
            st.session_state.locked_rules = edited_profile
            st.session_state.cache_key = cache_key
            st.session_state.stage = 2
            st.success("Absolute truth established and updated in cache database. Moving to Stage 2...")
            st.rerun()

# ==========================================
# 📊 STAGE 2: SEARCH TERMS AUDIT
# ==========================================
elif st.session_state.stage == 2:
    st.header(f"Stage 2: Audit Engine — Workspace: {st.session_state.cache_key}")
    
    uploaded_file = st.file_uploader("Upload Search Term Export (CSV Format)", type=["csv"], disabled=st.session_state.audit_running)
    
    BATCH_SIZE = 250
    
    if uploaded_file:
        try:
            uploaded_file.seek(0)
            df_preview = pd.read_csv(uploaded_file)
            term_col_preview = next((c for c in df_preview.columns if "search term" in c.lower() or "query" in c.lower()), None)
            
            if term_col_preview:
                raw_count = len(df_preview[term_col_preview].dropna().drop_duplicates())
                num_batches = (raw_count + BATCH_SIZE - 1) // BATCH_SIZE
                
                paid_seconds = max(int(num_batches * 1.5), 2)
                if paid_seconds >= 60:
                    paid_display = f"{paid_seconds // 60} min {paid_seconds % 60} sec" if paid_seconds % 60 > 0 else f"{paid_seconds // 60} min"
                else:
                    paid_display = f"{paid_seconds} seconds"
                
                st.warning(
                    f"📊 **Dataset Loaded:** {raw_count} unique search terms detected ({num_batches} loops of {BATCH_SIZE} rows).\n\n"
                    f"⏱️ **Precision Tier Speed Matrix:** Estimated completion in **{paid_display}**."
                )
            else:
                st.error("🛑 **Error Code: E005 - System Operational Failure**\n\nMissing Required Column Mapping. The uploaded file must contain a clear column titled either 'Search Term' or 'Query'.")
        except Exception as e:
            st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nFile read breakdown context failure: {str(e)}")

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
                    metric_slots[0].empty(), 
                    metric_slots[1].empty(), 
                    metric_slots[2].empty(), 
                    metric_slots[3].empty(),
                    metric_slots[4].empty()
                )
                
                relevant_list = []
                irrelevant_list = []
                review_list = []
                overlooked_list = []
                processed_terms_set = set()
                
                hit_processing_failure = False
                
                for i in range(0, total_input_count, BATCH_SIZE):
                    batch = search_terms[i:i + BATCH_SIZE]
                    counter_text.text(f"Processing Precision Matrix Chunk: Terms {i} to {min(i + BATCH_SIZE, total_input_count)} of {total_input_count}...")
                    
                    api_payload_batch = []
                    for term in batch:
                        if is_foreign_script(term):
                            irrelevant_list.append({
                                "Search Term": term,
                                "Confidence Score": 1.00,
                                "Reasoning": "Automated Guardrail: Detected foreign non-Latin alphabet character."
                            })
                            processed_terms_set.add(term)
                        else:
                            api_payload_batch.append(term)

                    if api_payload_batch:
                        try:
                            batch_results = classify_terms_batch(api_payload_batch, st.session_state.locked_rules)
                            
                            for res in batch_results:
                                term_string = res["search_term"]
                                processed_terms_set.add(term_string)
                                
                                row_data = {
                                    "Search Term": term_string,
                                    "Confidence Score": res["confidence"],
                                    "Reasoning": res["reason"]
                                }
                                if res["classification"] == "relevant":
                                    relevant_list.append(row_data)
                                elif res["classification"] == "irrelevant":
                                    irrelevant_list.append(row_data)
                                else:
                                    review_list.append(row_data)
                                    
                        except Exception as batch_err:
                            hit_processing_failure = True
                            for term in api_payload_batch:
                                if term not in processed_terms_set:
                                    overlooked_list.append({
                                        "Search Term": term, 
                                        "Confidence Score": 0.00, 
                                        "Reasoning": f"Bypass validation fallback loop segment: {str(batch_err)}"
                                    })
                                    processed_terms_set.add(term)
                    
                    percent_complete = int((min(i + BATCH_SIZE, total_input_count) / total_input_count) * 100)
                    progress_bar.progress(percent_complete)
                    
                    m1.metric("Processed", f"{len(processed_terms_set)}")
                    m2.metric("Relevant ✅", f"{len(relevant_list)}")
                    m3.metric("Irrelevant ❌", f"{len(irrelevant_list)}")
                    m4.metric("Review Queue 🔍", f"{len(review_list)}")
                    m5.metric("Overlooked ⚠️", f"{len(overlooked_list)}")
                    
                    if hit_processing_failure:
                        break

                for term in search_terms:
                    if term not in processed_terms_set:
                        overlooked_list.append({
                            "Search Term": term, 
                            "Confidence Score": 0.00, 
                            "Reasoning": "System reconciliation safety framework catch (Process Paused)"
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
                        
                    contains_protected = bool(phrase_words & protected_words)
                    
                    if contains_protected:
                        final_negatives_output.append(apply_ads_notation(phrase, is_exact=False))
                    else:
                        if not (phrase_words & active_root_words):
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
                    "relevant": relevant_list,
                    "irrelevant": irrelevant_list,
                    "review": review_list,
                    "overlooked": overlooked_list,
                    "roots": root_negatives_payload,
                    "copy_paste_list": final_negatives_output
                }
                st.session_state.audit_running = False
                st.success("Analysis matrix generated.")
                st.rerun()
                
            except Exception as main_err:
                st.session_state.audit_running = False
                st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nCore ledger computation failed on analysis layout execution: {str(main_err)}")

if st.session_state.audit_results:
    res_data = st.session_state.audit_results
    
    st.markdown("---")
    st.subheader("🛡️ Audit Summary Performance Data")
    
    if res_data["metrics"]["Potentially Overlooked Terms"] > 0:
        st.error(
            f"⚠️ **Classification Incomplete:** The engine was unsuccessful in classifying terms due to system processing risks. "
            f"The runthrough process has been paused to save API costs. Please check your parameters and try again in 10 mins."
        )
    
    met_cols = st.columns(6)
    metrics_mapping = [
        ("Total Inputted Terms", "Total Inputted Terms"),
        ("Relevant Terms", "Relevant ✅"),
        ("Irrelevant Terms", "Irrelevant ❌"),
        ("Review Queue Terms", "Review Queue 🔍"),
        ("Potentially Overlooked Terms", "Overlooked ⚠️"),
        ("Extracted Roots Count", "Extracted Roots 🌳")
    ]
    
    for idx, (metric_key, display_label) in enumerate(metrics_mapping):
        with met_cols[idx]:
            val = res_data["metrics"].get(metric_key, 0)
            st.markdown(f'<p class="metric-bold-label">{display_label}</p>', unsafe_allow_html=True)
            st.markdown(f'<p class="metric-bold-value">{val}</p>', unsafe_allow_html=True)

    st.markdown("---")
    
    # Grid Breakdown Panels
    col_out1, col_out2 = st.columns([7, 3])
    
    with col_out1:
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "❌ Irrelevant Terms", 
            "🌳 Extracted Roots", 
            "🔍 Review Queue", 
            "✅ Relevant Terms", 
            "⚠️ Overlooked"
        ])
        
        with tab1:
            if res_data["irrelevant"]:
                st.dataframe(pd.DataFrame(res_data["irrelevant"]), use_container_width=True, hide_index=True)
            else:
                st.info("No irrelevant terms found.")
                
        with tab2:
            if res_data["roots"]:
                st.dataframe(pd.DataFrame(res_data["roots"]), use_container_width=True, hide_index=True)
            else:
                st.info("No root negative combinations extracted.")
                
        with tab3:
            if res_data["review"]:
                st.dataframe(pd.DataFrame(res_data["review"]), use_container_width=True, hide_index=True)
            else:
                st.info("Review queue is clear.")
                
        with tab4:
            if res_data["relevant"]:
                st.dataframe(pd.DataFrame(res_data["relevant"]), use_container_width=True, hide_index=True)
            else:
                st.info("No matching relevant parameters found.")
                
        with tab5:
            if res_data["overlooked"]:
                st.dataframe(pd.DataFrame(res_data["overlooked"]), use_container_width=True, hide_index=True)
            else:
                st.info("Zero bypassed exceptions encountered.")

    with col_out2:
        st.subheader("⚙️ Workspace Controls")
        st.caption("Need to Sanity Check the Outputs? Download the below Workbook Ledger.")
        
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
                    sheet_url = push_to_google_sheets(st.session_state.cache_key, payload)
                    st.success("Workbook Ledger generated successfully!")
                    st.markdown(f'[🔗 Open Google Sheet Ledger]({sheet_url})', unsafe_allow_html=True)
                except Exception as sheet_err:
                    st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nSheet integration failed to finalize target workbook: {str(sheet_err)}")

        st.markdown("### 📋 Copy/Paste Negative List")
        st.caption("Raw Broad/Phrase formatted keywords to insert straight into your Google Ads campaigns.")
        neg_text = "\n".join(res_data["copy_paste_list"])
        st.text_area("Google Ads Clipboard Payload", value=neg_text, height=250)
