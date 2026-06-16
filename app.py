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
    # Disable back button navigation while processing to maintain state integrity
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

st.write(f"Key exists in secrets: {'GEMINI_API_KEY' in st.secrets}")

# ==========================================
# 🔥 STAGE 1: BRAND UNDERSTANDING AUDIT
# ==========================================
if st.session_state.stage == 1:
    st.header("Stage 1: Brand Understanding Audit")
    
    cache_options = get_cached_profiles()
    selected_cache = st.selectbox("Select a Profile Configuration Template", options=cache_options, index=0)
    
    if selected_cache != "Create New":
        if st.session_state.brand_profile is None:
            try:
                st.session_state.brand_profile = load_cached_profile(selected_cache)
                
                cache_parts = selected_cache.split(" | ")
                if len(cache_parts) == 3:
                    st.session_state.temp_brand_name = cache_parts[0]
                    st.session_state.temp_campaign_type = cache_parts[1]
                    st.session_state.temp_core_offering = cache_parts[2]
                else:
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
            height=120
        )
        
        if st.button("Launch Brand Understanding Audit"):
            if not brand_name or campaign_type == "-Please Select-" or not core_offering or not landing_pages:
                st.error("🛑 **Error Code: E001 - Missing Input Parameters**\n\nOne or more required input fields were left blank or unselected.")
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
                        st.error("📡 **Error Code: E004 - Cloud Connection Dropped**\n\nThe connection to the Google Cloud AI loop was dropped mid-process.")
                    else:
                        st.error(f"🔧 **Error Code: E005 - System Operational Failure**\n\nAn unexpected backend processing anomaly occurred. Details: {str(e)}")

    st.session_state.last_selected_cache = selected_cache

    if st.session_state.brand_profile:
        st.markdown("### 📝 Refine Brand Understanding Rulesets")
        st.caption("Double-click individual cells to add custom items, clear rows, or correct terms before cementing absolute rules.")
        
        edited_profile = {}
        
        # Row 1: Brand & Protected Core
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
        
        # Row 2: Competitors & Irrelevant Concepts
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
            
        st.markdown("<br>", unsafe_allow_html=True)

        # 🌐 Row 3: 5th Box - Allowed Languages Matrix
        st.markdown("#### 🌐 Allowed Target Languages & Regions")
        default_languages = st.session_state.brand_profile.get("allowed_languages", ["English"])
        df_lang = pd.DataFrame(default_languages, columns=["Target Languages"])
        ed_lang = st.data_editor(df_lang, num_rows="dynamic", use_container_width=False, width=400, key="editor_lang")
        edited_profile["allowed_languages"] = ed_lang["Target Languages"].dropna().tolist()
            
        st.markdown("---")
        
        if st.button("Confirm and Update Brand Knowledge Base", type="primary"):
            b_title = st.session_state.get("temp_brand_name", "Brand").strip()
            t_title = st.session_state.get("temp_campaign_type", "Search").strip()
            c_title = st.session_state.get("temp_core_offering", "Offering").strip()
            
            cache_key = f"{b_title} | {t_title} | {c_title}"
            save_profile_to_cache(cache_key, edited_profile)
            
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
    
    # Block file adjustments while calculations are actively happening
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

    # Dynamic button context changes text and locks immediately when running switches to True
    button_text = "Processing Audit Engine Matrix..." if st.session_state.audit_running else "Launch Search Terms Audit"
    
    if st.button(button_text, type="secondary", use_container_width=True, disabled=st.session_state.audit_running):
        if not uploaded_file:
            st.error("🛑 **Error Code: E002 - Missing File Stream**\n\nThe Search Term Ledger dataset CSV upload path is missing.")
        else:
            st.session_state.audit_running = True
            st.rerun()

    # Split processing runtime zone
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
                # Unlatch UI runtime lock configuration variables
                st.session_state.audit_running = False
                st.success("Analysis matrix generated.")
                st.rerun()
                
            except Exception as main_err:
                # Release execution lock parameters on backend failures to prevent locked UI
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
    
    col_views = st.columns(2)
    with col_views[0]:
        with st.expander("🔍 Standard Review Queue View", expanded=True):
            df_rev = pd.DataFrame(res_data["review"])
            st.dataframe(df_rev, use_container_width=True, hide_index=True)
            if not df_rev.empty:
                st.download_button("Download Review Queue CSV", data=df_rev.to_csv(index=False), file_name="review_queue_dump.csv", key="btn_dl_rev")
                
    with col_views[1]:
        with st.expander("⚠️ Potentially Overlooked Isolation Queue", expanded=True):
            df_ovr = pd.DataFrame(res_data["overlooked"])
            st.dataframe(df_ovr, use_container_width=True, hide_index=True)
            if not df_ovr.empty:
                st.download_button("Download Overlooked Queue CSV", data=df_ovr.to_csv(index=False), file_name="overlooked_queue_dump.csv", key="btn_dl_ovr")
            else:
                st.info("System operational health stable. Zero terms bypassed to fallback parameters.")
                
    st.markdown("<br>", unsafe_allow_html=True)
            
    col_out1, col_out2 = st.columns([2, 1])
    with col_out1:
        st.subheader("🎯 Optimization Output: Google Ads Copy-Paste Match List")
        st.caption("Copy this target data string completely straight onto campaign parameters negative target keywords list inputs.")
        text_block = "\n".join(res_data["copy_paste_list"])
        st.text_area("Ready Matrix List Output Data Box", value=text_block, height=350)
        
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
