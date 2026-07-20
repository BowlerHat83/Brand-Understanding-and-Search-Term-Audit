# --- CRUCIAL CLOUD PATH PATCH (MUST BE LINES 1-3) ---
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import json
import re
import asyncio  # 🏎️ Core Async engine integration
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# --- RE-MAPPED TO MATCH YOUR EXACT GITHUB FILENAMES ---
from backend_stage1 import run_brand_audit
from backend_stage2 import classify_terms_batch, extract_root_negatives, apply_ads_notation
from backend_stage3 import push_to_google_sheets

# --- INITIAL APP SETUP & STATE MANAGEMENT ---
st.set_page_config(page_title="Negative Keyword Architect", layout="wide")

# Clean layout style tracking without any button color overrides
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

# --- BULLETPROOF LOCAL CACHE STORAGE HUB ---
LOCAL_CACHE_FILE = "brand_cache.json"

def get_local_cache():
    if os.path.exists(LOCAL_CACHE_FILE):
        with open(LOCAL_CACHE_FILE, "r") as f:
            try: return json.load(f)
            except: return {}
    return {}

def filter_local_cache_by_workspace(workspace_key):
    cache = get_local_cache()
    if workspace_key in cache:
        return cache[workspace_key]
    return {"relevant": [], "irrelevant": [], "review": []}

def save_audit_to_local_cache(workspace_key, relevant_terms, irrelevant_terms):
    cache = get_local_cache()
    if workspace_key not in cache:
        cache[workspace_key] = {"relevant": [], "irrelevant": [], "review": []}
    for term in relevant_terms:
        if term not in cache[workspace_key]["relevant"]:
            cache[workspace_key]["relevant"].append(term)
    for term in irrelevant_terms:
        if term not in cache[workspace_key]["irrelevant"]:
            cache[workspace_key]["irrelevant"].append(term)
    with open(LOCAL_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=4)

# --- BULLETPROOF GOOGLE SHEETS CACHE LAYER ---
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def safe_split_cell(cell_value):
    if not cell_value: return []
    clean_value = str(cell_value).strip("[]\"'")
    return [item.strip() for item in clean_value.split(",") if item.strip()]

def get_cached_profiles():
    try:
        gc = get_gspread_client()
        sheet = gc.open_by_key(st.secrets["CACHE_SPREADSHEET_ID"]).sheet1
        records = sheet.get_all_records()
        profile_names = [row["Profile Name"] for row in records if row.get("Profile Name")]
        return ["Create New"] + sorted(profile_names, key=str.lower)
    except:
        return ["Create New"]

def load_cached_profile(profile_name):
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

def is_foreign_script(text):
    if re.search(r'[^\x00-\x7F\u00C0-\u017F\s\d.,&\'"\-_+/()!]', text):
        return True
    return False

# --- ASYNC EXECUTOR BRIDGE ---
async def async_classify_wrapper(batch, rules):
    """Executes the legacy backend function safely inside an isolated thread worker."""
    return await asyncio.to_thread(classify_terms_batch, batch, rules)

# --- APP STATES ---
if "stage" not in st.session_state: st.session_state.stage = 1
if "brand_profile" not in st.session_state: st.session_state.brand_profile = None
if "locked_rules" not in st.session_state: st.session_state.locked_rules = None
if "audit_results" not in st.session_state: st.session_state.audit_results = None

# ==========================================
# 🗺️ PERSISTENT NAVIGATION HUB
# ==========================================
st.title("🛡️ Google Ads Negative Keyworder")
st.write("Google Ads Classification System built on an expanding Brand Knowledge Base.")

nav_cols = st.columns([1, 4, 1])
with nav_cols[0]:
    if st.session_state.stage > 1:
        if st.button("⬅️ Back to Stage 1", use_container_width=True):
            st.session_state.stage = 1
            st.session_state.brand_profile = None
            st.session_state.locked_rules = None
            st.session_state.audit_results = None
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
            unique_brands.add(option.split(" | ")[0].strip())
            
    brand_list = ["-Please Select-", "Create New"] + sorted(list(unique_brands), key=str.lower)
    col_b1, col_b2 = st.columns(2)
    
    with col_b1:
        selected_brand_tier = st.selectbox("🏢 Select Brand Portfolio", options=brand_list, index=0)
        
    selected_cache = "Create New"
    with col_b2:
        if selected_brand_tier not in ["-Please Select-", "Create New"]:
            matching_workspaces = [o.replace(f"{selected_brand_tier} | ", "").strip() for o in cache_options if o.startswith(f"{selected_brand_tier} | ")]
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
    elif selected_cache != "Create New":
        if st.session_state.brand_profile is None or st.session_state.get('cache_key') != selected_cache:
            st.session_state.brand_profile = load_cached_profile(selected_cache)
            cache_parts = selected_cache.split(" | ")
            st.session_state.temp_brand_name = cache_parts[0]
            st.session_state.temp_campaign_type = cache_parts[1] if len(cache_parts) > 1 else "Search"
            st.session_state.temp_ad_group_name = cache_parts[2] if len(cache_parts) > 2 else ""
            st.session_state.locked_rules = st.session_state.brand_profile
            st.session_state.cache_key = selected_cache
                
        st.success(f"📋 Loaded configuration workspace layout baseline: **{selected_cache}**")
        r1l, r1r = st.columns(2)
        r1l.selectbox("Brand Name", options=[st.session_state.temp_brand_name], disabled=True)
        r1r.selectbox("Campaign Type", options=[st.session_state.temp_campaign_type], disabled=True)
    else:
        row1_left, row1_right = st.columns(2)
        brand_name = row1_left.text_input("Brand Name", value="")
        campaign_type = row1_right.selectbox("Campaign Type", options=["-Please Select-", "Search", "PMax", "Display", "Shopping"])
        row2_left, row2_right = st.columns(2)
        ad_group_name = row2_left.text_input("Ad Group Name", value="")
        core_offering = row2_right.text_input("Core Offering of the Ad Group", value="")
        landing_pages = st.text_area("Target Landing Page Links & Context", height=120)
        
        if st.button("Launch Brand Understanding Audit"):
            if not brand_name or campaign_type == "-Please Select-" or not ad_group_name or not core_offering:
                st.error("🛑 Missing Input Parameters.")
            else:
                raw_profile = run_brand_audit(brand_name, core_offering, landing_pages)
                st.session_state.brand_profile = raw_profile
                st.session_state.temp_brand_name = brand_name
                st.session_state.temp_campaign_type = campaign_type
                st.session_state.temp_ad_group_name = ad_group_name
                st.session_state.temp_core_offering = core_offering
                st.rerun()

    if st.session_state.brand_profile:
        st.markdown("### 📝 Refine Brand Understanding Rulesets")
        edited_profile = {}
        active_w_key = st.session_state.get("cache_key", f"{st.session_state.get('temp_brand_name','B')} | {st.session_state.get('temp_campaign_type','S')} | {st.session_state.get('temp_ad_group_name','A')}")
        local_historical_assets = filter_local_cache_by_workspace(active_w_key)
        
        def l2s(lst): return "\n".join([str(x).strip() for x in lst if str(x).strip()])
        def s2l(txt): return [line.strip() for line in txt.split("\n") if line.strip()]

        with st.expander("✨ View/Edit Allowed Brand Variants & Misspellings"):
            edited_profile["brand_variants"] = s2l(st.text_area("Enter Brand Variants:", value=l2s(st.session_state.brand_profile.get("brand_variants", [])), height=120))
        with st.expander("🛡️ View/Edit Protected Core Offering Terms"):
            edited_profile["protected_terms"] = s2l(st.text_area("Enter Protected Core Terms:", value=l2s(st.session_state.brand_profile.get("protected_terms", [])), height=120))
        with st.expander("🚨 View/Edit Competitor Target Brand Names"):
            edited_profile["competitors"] = s2l(st.text_area("Enter Competitor Brands:", value=l2s(st.session_state.brand_profile.get("competitors", [])), height=120))
        with st.expander("❌ View/Edit Clear Irrelevant Elements & Concepts"):
            edited_profile["irrelevant_terms"] = s2l(st.text_area("Enter Irrelevant Concepts:", value=l2s(st.session_state.brand_profile.get("irrelevant_terms", [])), height=120))
        with st.expander("🌐 View/Edit Allowed Target Languages"):
            edited_profile["allowed_languages"] = s2l(st.text_area("Enter Target Languages:", value=l2s(st.session_state.brand_profile.get("allowed_languages", ["English"])), height=80))
            
        if st.button("Confirm and Update Brand Knowledge Base", type="primary"):
            cache_key = f'{st.session_state.temp_brand_name} | {st.session_state.temp_campaign_type} | {st.session_state.temp_ad_group_name}'
            save_profile_to_cache(cache_key, edited_profile)
            st.session_state.locked_rules = edited_profile
            st.session_state.cache_key = cache_key
            st.session_state.stage = 2
            st.rerun()
            
# ==========================================
# 📊 STAGE 2: ATOMIC FRAGMENT EXECUTION ENGINE
# ==========================================
elif st.session_state.stage == 2:
    st.header(f"Stage 2: Audit Engine — Workspace: {st.session_state.cache_key}")
    uploaded_file = st.file_uploader("Upload Search Term Export (CSV Format)", type=["csv"])

    # 🏎️ COMPACT CONCURRENT EXECUTION CONTAINER FRAGMENT WITH LIVE COUNTER
    @st.fragment
    def render_execution_engine(csv_file):
        if csv_file is not None:
            try:
                csv_file.seek(0)
                df_input = pd.read_csv(csv_file)
                term_col = next((c for c in df_input.columns if "search term" in c.lower() or "query" in c.lower()), None)
                
                if not term_col:
                    st.error("Missing Search Term or Query column layout.")
                    return

                search_terms = df_input[term_col].dropna().drop_duplicates().tolist()
                total_count = len(search_terms)
                
                st.info(f"📊 **Dataset Loaded:** {total_count} unique queries identified.")
                
                if st.button("🚀 Launch High-Speed Async Audit Run", type="primary", use_container_width=True):
                    status_lbl = st.empty()
                    
                    # 1. High Speed Local Vector Pre-Filtering Layer
                    relevant_list, irrelevant_list, review_list, overlooked_list = [], [], [], []
                    api_queue = []
                    
                    for term in search_terms:
                        if is_foreign_script(term):
                            irrelevant_list.append({"Search Term": term, "Confidence Score": 1.0, "Reasoning": "Auto-Filter: Non-Latin characters."})
                        else:
                            api_queue.append(term)
                            
                    # 2. Slice Queue into Concurrent Batch Loads
                    BATCH_SIZE = 100
                    batches = [api_queue[x:x+BATCH_SIZE] for x in range(0, len(api_queue), BATCH_SIZE)]
                    total_batches = len(batches)
                    
                    # Track completed tasks in real-time
                    completed_batches = 0
                    
                    # Core Wallet Protector: Cap connections strictly to 5 at a time
                    sem = asyncio.Semaphore(5)
                    
                    async def wrapped_task(index, batch, rules, lock):
                        nonlocal completed_batches
                        # Acquire semaphore slot before firing the API call
                        async with sem:
                            try:
                                # Ensure the async wrapper is fully executed and completed
                                res = await async_classify_wrapper(batch, rules)
                                
                                # If the wrapper returned another coroutine object by mistake, resolve it
                                if inspect.iscoroutine(res):
                                    res = await res
                                    
                                async with lock:
                                    completed_batches += 1
                                    status_lbl.markdown(f"⚡ **Processing Matrix:** Completed `{completed_batches}/{total_batches}` batches... (Remaining: {total_batches - completed_batches})")
                                return res
                            except Exception as e:
                                async with lock:
                                    completed_batches += 1
                                return e

                    async def process_all_concurrently():
                        lock = asyncio.Lock()
                        tasks = [wrapped_task(i, b, st.session_state.locked_rules, lock) for i, b in enumerate(batches)]
                        return await asyncio.gather(*tasks)
                    
                    # 3. Streamlit Spinner Visual Trust Gateway
                    with st.spinner(f"📡 Matrix Engine Active: Dispatching {total_batches} parallel API threads..."):
                        status_lbl.markdown(f"⚡ **Processing Matrix:** Completed `0/{total_batches}` batches... (Remaining: {total_batches})")
                        
                        # Set up clean event loop execution context
                        try:
                            loop = asyncio.get_event_loop()
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            
                        loop_results = loop.run_until_complete(process_all_concurrently())
                    
                    # 4. Assemble payloads instantly without UI thrashing loops
                    status_lbl.markdown("📝 **Assembling final matrix ledgers...**")
                    for index, res_block in enumerate(loop_results):
                        if isinstance(res_block, Exception):
                            failed_batch = batches[index]
                            for term in failed_batch:
                                overlooked_list.append({"Search Term": term, "Confidence Score": 0.0, "Reasoning": f"Async block failed: {str(res_block)}"})
                            continue
                            
                        # Bulletproof type check: ensure the block is iterable and not a lingering coroutine
                        if res_block is not None and not inspect.iscoroutine(res_block):
                            for res in res_block:
                                if isinstance(res, dict):
                                    row_data = {
                                        "Search Term": res.get("search_term", ""), 
                                        "Confidence Score": res.get("confidence", 1.0), 
                                        "Reasoning": res.get("reason", "")
                                    }
                                    cls = str(res.get("classification", "review")).lower().strip()
                                    if cls == "relevant": relevant_list.append(row_data)
                                    elif cls == "irrelevant": irrelevant_list.append(row_data)
                                    else: review_list.append(row_data)
                        else:
                            # Fallback if a batch payload returned completely corrupted or un-awaited
                            failed_batch = batches[index]
                            for term in failed_batch:
                                overlooked_list.append({"Search Term": term, "Confidence Score": 0.0, "Reasoning": "Pipeline processing anomaly."})
                    
                    # 5. Final Core Analytics & Negative Optimization Extraction Build
                    irr_phrases = [r["Search Term"] for r in irrelevant_list]
                    saved_phrases = [r["Search Term"] for r in relevant_list] + [r["Search Term"] for r in review_list] + [r["Search Term"] for r in overlooked_list]
                    
                    raw_roots = extract_root_negatives(irr_phrases, saved_phrases, st.session_state.locked_rules.get("protected_terms", []))
                    root_payload = [{"Root Word": w, "Blocked Volume Count": c, "Ads Notation Match": apply_ads_notation(w, is_exact=False)} for w, c in raw_roots.items()]
                    
                    copy_paste_out = [rn["Ads Notation Match"] for rn in root_payload]
                    for irr in irrelevant_list:
                        copy_paste_out.append(apply_ads_notation(irr["Search Term"], is_exact=False))
                    copy_paste_out = list(set(copy_paste_out))
                    
                    st.session_state.audit_results = {
                        "metrics": {
                            "Total Inputted Terms": total_count, "Relevant Terms": len(relevant_list), "Irrelevant Terms": len(irrelevant_list),
                            "Review Queue Terms": len(review_list), "Potentially Overlooked Terms": len(overlooked_list), "Extracted Roots Count": len(root_payload)
                        },
                        "relevant": relevant_list, "irrelevant": irrelevant_list, "review": review_list, "overlooked": overlooked_list,
                        "roots": root_payload, "copy_paste_list": copy_paste_out
                    }
                    status_lbl.empty()
                    st.rerun()
            except Exception as e:
                st.error(f"Execution run crashed: {str(e)}")

    # Add inspect import to top of your workspace definitions if not already present
    import inspect
    render_execution_engine(uploaded_file)

# ==========================================
# 📊 OUTPUT SUMMARY & BATCH TRIAGE
# ==========================================
if st.session_state.get("audit_results") is not None:
    res_data = st.session_state.audit_results
    st.markdown("---")
    st.subheader("🛡️ Audit Summary Performance Data")
    
    overlooked_count = res_data["metrics"]["Potentially Overlooked Terms"]
    if overlooked_count > 0:
        st.error(f"🚨 **Attention Required:** {overlooked_count} terms bypassed automated pipelines and are held inside the overlooked ledger queue.")
    
    met_cols = st.columns(6)
    metrics_mapping = [
        ("Total Inputted Terms", "Total Inputted Terms"), ("Relevant Terms ✅", "Relevant Terms"), ("Irrelevant Terms ❌", "Irrelevant Terms"),
        ("Review Queue 🔍", "Review Queue Terms"), ("Potentially Overlooked ⚠️", "Potentially Overlooked Terms"), ("Extracted Roots Count 🪵", "Extracted Roots Count")
    ]
    for idx, (label, key) in enumerate(metrics_mapping):
        with met_cols[idx]:
            st.markdown(f'<div class="metric-bold-label">{label}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-bold-value">{res_data["metrics"][key]}</div>', unsafe_allow_html=True)
            
    st.markdown("<br>", unsafe_allow_html=True)
    from backend_stage3 import update_brand_profile_cache

    if "triage_list" not in st.session_state:
        st.session_state.triage_list = [item["Search Term"] for item in res_data["review"]] + [item["Search Term"] for item in res_data["overlooked"]]
    if "cache_committed" not in st.session_state:
        st.session_state.cache_committed = False

    split_left, split_right = st.columns([1, 1])
    
    with split_left:
        st.subheader("🔍 Review Queue Triage Desk")
        if st.session_state.triage_list:
            checked_count = sum([1 for index, term in enumerate(st.session_state.triage_list) if st.session_state.get(f"triage_chk_row_{term}_{index}", False)])
            total_items = len(st.session_state.triage_list)
            maj_sel = checked_count > (total_items / 2)
            toggle_label = "⬜ Deselect All" if maj_sel else "✅ Select All"
            
            act_col1, act_col2, act_col3 = st.columns(3)
            if act_col1.button(toggle_label, use_container_width=True):
                for index, term in enumerate(st.session_state.triage_list):
                    st.session_state[f"triage_chk_row_{term}_{index}"] = not maj_sel
                st.rerun()
                
            trigger_move_relevant = act_col2.button("👍 Move to Relevant", use_container_width=True)
            trigger_move_irrelevant = act_col3.button("👎 Move to Irrelevant", use_container_width=True)
            
            selected_terms = []
            st.markdown("<br>", unsafe_allow_html=True)
            with st.container(height=350):
                for index, term in enumerate(st.session_state.triage_list):
                    row_cols = st.columns([1, 9])
                    is_selected = row_cols[0].checkbox(" ", key=f"triage_chk_row_{term}_{index}", label_visibility="collapsed")
                    row_cols[1].text(term)
                    if is_selected: selected_terms.append(term)
                    
            if trigger_move_relevant or trigger_move_irrelevant:
                if not selected_terms:
                    st.warning("⚠️ No checkboxes selected.")
                else:
                    if trigger_move_relevant:
                        for t in selected_terms:
                            if not any(r["Search Term"] == t for r in res_data["relevant"]):
                                res_data["relevant"].append({"Search Term": t, "Confidence Score": 1.0, "Reasoning": "Human Triage Map"})
                    else:
                        for t in selected_terms:
                            if not any(r["Search Term"] == t for r in res_data["irrelevant"]):
                                res_data["irrelevant"].append({"Search Term": t, "Confidence Score": 1.0, "Reasoning": "Human Triage Map"})
                                notation = apply_ads_notation(t, is_exact=False)
                                if notation not in res_data["copy_paste_list"]: res_data["copy_paste_list"].append(notation)
                                
                    st.session_state.triage_list = [t for t in st.session_state.triage_list if t not in selected_terms]
                    res_data["review"] = [r for r in res_data["review"] if r["Search Term"] not in selected_terms]
                    res_data["overlooked"] = [o for o in res_data["overlooked"] if o["Search Term"] not in selected_terms]
                    res_data["metrics"]["Review Queue Terms"] = len(res_data["review"])
                    res_data["metrics"]["Potentially Overlooked Terms"] = len(res_data["overlooked"])
                    res_data["metrics"]["Relevant Terms"] = len(res_data["relevant"])
                    res_data["metrics"]["Irrelevant Terms"] = len(res_data["irrelevant"])
                    st.session_state.cache_committed = False
                    st.session_state.audit_results = res_data
                    st.rerun()
        else:
            st.info("🎉 All items fully triaged inside this active configuration run.")

    with split_right:
        st.subheader("🎯 Optimization Output: Google Ads Copy-Paste Match List")
        text_block = "\n".join(res_data["copy_paste_list"])
        st.text_area("Ready Matrix List Output Data Box", value=text_block, height=350)
        
        with st.expander("⚠️ Review Potentially Overlooked Terms Pipeline Ledger"):
            overlooked_items = [o["Search Term"] for o in res_data.get("overlooked", [])]
            if overlooked_items:
                for item in overlooked_items: st.text(f"• {item}")
            else: st.info("No bypass terms detected inside threshold parameters.")

    # =========================================================================
    # 3. FULL-WIDTH WORKSPACE CONTROLS FOOTER (CLEAN DEFAULT THEME DESIGN)
    # =========================================================================
    st.subheader("⚙️ Global Workspace Controls")
    
    foot_col1, foot_col2, foot_col3 = st.columns(3)
    with foot_col1:
        payload = {"Metrics Data": [{"Metric Name": k, "Value": v} for k, v in res_data["metrics"].items()], "Relevant Search Terms": res_data["relevant"], "Irrelevant Search Terms": res_data["irrelevant"], "Review Queue": res_data["review"], "Potentially Overlooked": res_data["overlooked"], "Root Negatives": res_data["roots"]}
        csv_stream = push_to_google_sheets(st.session_state.cache_key, payload)
        if csv_stream is not None:
            st.download_button(label="🚀 Download Workbook Ledger (.csv)", data=csv_stream, file_name=f"Negative_Optimization_Ledger_{st.session_state.cache_key.replace(' | ', '_')}.csv", mime="text/csv", use_container_width=True)

    with foot_col2:
        cache_btn_label = "✅ Audit Knowledge Cached" if st.session_state.cache_committed else "💾 Cache Audit into Brand Knowledge"
        if st.button(cache_btn_label, use_container_width=True, disabled=st.session_state.cache_committed):
            profile_sig = st.session_state.cache_key.split(" | ")[0].strip() if " | " in st.session_state.cache_key else st.session_state.cache_key
            rel_payload = [r["Search Term"] for r in res_data["relevant"]]
            irr_payload = [i["Search Term"] for i in res_data["irrelevant"]]
            save_audit_to_local_cache(st.session_state.cache_key, rel_payload, irr_payload)
            success = update_brand_profile_cache(cache_key=profile_sig, new_relevant_terms=rel_payload, new_irrelevant_terms=irr_payload)
            if success:
                st.session_state.cache_committed = True
                st.success("All data files updated.")
                st.rerun()

    with foot_col3:
        if st.button("🔄 Start New Audit", use_container_width=True):
            for index, term in enumerate(st.session_state.get("triage_list", [])):
                key_to_clear = f"triage_chk_row_{term}_{index}"
                if key_to_clear in st.session_state: del st.session_state[key_to_clear]
            if "triage_list" in st.session_state: del st.session_state.triage_list
            if "audit_results" in st.session_state: del st.session_state.audit_results
            st.session_state.stage = 1
            st.session_state.brand_profile = None
            st.session_state.locked_rules = None
            st.rerun()
