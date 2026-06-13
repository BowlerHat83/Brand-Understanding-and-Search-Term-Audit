import streamlit as st
import pandas as pd
import json
import os
import time
import threading

# Import backend modules
import backend_stage1
import backend_stage2
import backend_stage3

st.set_page_config(page_title="Negative Keyword Intelligence System", layout="wide")

if "stage" not in st.session_state: st.session_state.stage = 1
if "brand_understanding" not in st.session_state: st.session_state.brand_understanding = None
if "locked_truth" not in st.session_state: st.session_state.locked_truth = None
if "classification_results" not in st.session_state: st.session_state.classification_results = None
if "root_negatives" not in st.session_state: st.session_state.root_negatives = None

CACHE_DIR = "brand_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def run_smooth_progress(target_function, args, success_message="Complete!"):
    """Wrapper that smoothly updates the UI progress bar while background tasks process."""
    progress_bar = st.progress(0)
    status_msg = st.empty()
    
    result_container = {}
    
    def worker():
        try:
            result_container['data'] = target_function(*args)
        except Exception as e:
            result_container['error'] = str(e)

    # Spawn thread to run background API tasks without blocking main thread
    t = threading.Thread(target=worker)
    t.start()
    
    current_progress = 0
    while t.is_alive():
        # Gradually fill the loading bar up to 95% while waiting
        if current_progress < 95:
            current_progress += 5
            progress_bar.progress(current_progress)
            status_msg.info(f"Processing data streams... {current_progress}%")
        time.sleep(0.15)
        
    progress_bar.progress(100)
    status_msg.success(success_message)
    time.sleep(0.4)
    progress_bar.empty()
    status_msg.empty()
    
    return result_container.get('data', {"error": result_container.get('error', 'Unknown execution fault')})

# --- STAGE 1 UI ROUTING ---
if st.session_state.stage == 1:
    st.title("🛡️ Stage 1: Brand Audit Horizon")
    st.markdown("---")
    
    cached_profiles = ["Create New"] + [f.replace(".json", "") for f in os.listdir(CACHE_DIR) if f.endswith(".json")]
    selected_profile = st.selectbox("Select Active Operational Profile", cached_profiles)
    
    if selected_profile != "Create New":
        if st.button("Load Configuration Profile"):
            with open(os.path.join(CACHE_DIR, f"{selected_profile}.json"), "r") as f:
                st.session_state.locked_truth = json.load(f)
            st.session_state.stage = 2
            st.rerun()
    else:
        brand_name = st.text_input("Brand Name", placeholder="e.g., Apex Ventures")
        core_offering = st.text_input("Core Offering", placeholder="e.g., B2B Cloud Logistics Monitoring")
        landing_page = st.text_input("Landing Page Link", placeholder="https://example.com")
        
        if st.button("Launch Brand Understanding Audit"):
            if not brand_name: st.error("🚨 ERR_AUTH_01: Missing Brand Name.")
            elif not core_offering: st.error("🚨 ERR_AUTH_02: Missing Core Offering.")
            elif not landing_page: st.error("🚨 ERR_AUTH_03: Missing Landing Page Link.")
            else:
                # Trigger smooth animated loader
                res = run_smooth_progress(
                    backend_stage1.analyze_brand_profile, 
                    (brand_name, core_offering, landing_page),
                    "Profile Formulated!"
                )
                
                if isinstance(res, dict) and "error" in res:
                    st.error(res["error"])
                else:
                    st.session_state.brand_understanding = res
                    st.session_state.current_brand_name = brand_name
                    st.session_state.current_core_offering = core_offering

        if st.session_state.brand_understanding:
            st.markdown("### ✍️ Refine Knowledge Profile")
            bv = st.data_editor(st.session_state.brand_understanding.get("brand_variants", []), num_rows="dynamic", key="ebv")
            cb = st.data_editor(st.session_state.brand_understanding.get("competitor_brands", []), num_rows="dynamic", key="ecb")
            pt = st.data_editor(st.session_state.brand_understanding.get("protected_terms", []), num_rows="dynamic", key="ept")
            ni = st.data_editor(st.session_state.brand_understanding.get("irrelevant_niches", []), num_rows="dynamic", key="eni")
            
            if st.button("Confirm & Lock Base Truth"):
                final_truth = {"brand_variants": bv, "competitor_brands": cb, "protected_terms": pt, "irrelevant_niches": ni}
                name = f"{st.session_state.current_brand_name} | {st.session_state.current_core_offering}".replace("/", "-")
                with open(os.path.join(CACHE_DIR, f"{name}.json"), "w") as f:
                    json.dump(final_truth, f)
                st.session_state.locked_truth = final_truth
                st.session_state.stage = 2
                st.rerun()

# --- STAGE 2 UI ROUTING ---
elif st.session_state.stage == 2:
    st.title("🔍 Stage 2: Target Classification Engine")
    uploaded_file = st.file_uploader("Upload Search Terms CSV File Source", type=["csv"])
    
    if st.button("Launch Search Terms Audit"):
        if not uploaded_file:
            st.error("🚨 ERR_DATA_01: Missing Uploaded CSV Stream Source File.")
        else:
            df_input = pd.read_csv(uploaded_file)
            col = [c for c in df_input.columns if 'term' in c.lower() or 'query' in c.lower()][0]
            raw_terms = df_input[col].dropna().astype(str).unique().tolist()
            
            # Sub-function helper for processing split-batch data sequences cleanly inside thread wrapper
            def batch_processing_wrapper(terms, truth):
                all_results = []
                batch_size = 150
                for i in range(0, len(terms), batch_size):
                    batch_res = backend_stage2.classify_search_terms_batch(terms[i:i+batch_size], truth)
                    all_results.extend(batch_res)
                return all_results

            # Pass the batch logic to our smooth loader framework
            results = run_smooth_progress(batch_processing_wrapper, (raw_terms, st.session_state.locked_truth), "Terms Audit Finalized!")
            df_classified = pd.DataFrame(results)
            
            if len(raw_terms) != len(df_classified):
                st.error("🚨 ERR_PIPELINE_MISMATCH: Row delta logic error detected between payload stages.")
                
            st.session_state.root_negatives = backend_stage2.calculate_root_negatives(df_classified)
            st.session_state.classification_results = df_classified
            st.session_state.total_input_count = len(raw_terms)

    if st.session_state.classification_results is not None:
        df_res = st.session_state.classification_results
        st.metric("Total Rows Processed Successfully", st.session_state.total_input_count)
        
        t1, t2 = st.columns(2)
        with t1:
            st.subheader("🟡 Review Queue Allocation Tracking")
            st.dataframe(df_res[df_res['classification'] == 'review'][['term', 'confidence_score']], use_container_width=True)
        with t2:
            st.subheader("📋 Direct Copy Punctuation Formats")
            formatted = backend_stage2.generate_google_ads_notation(df_res, st.session_state.root_negatives)
            st.code("\n".join(formatted), language="text")
            
        if st.button("Proceed to Ledger System (Stage 3)"):
            st.session_state.stage = 3
            st.rerun()
        if st.button("Start Completely New Audit"):
            st.session_state.clear()
            st.rerun()

# --- STAGE 3 UI ROUTING ---
elif st.session_state.stage == 3:
    st.title("🗂️ Stage 3: Output Spreadsheet Distributions")
    
    if st.button("📥 Build & Compile Excel Ledger Sheet"):
        df_res = st.session_state.classification_results
        metrics = pd.DataFrame([{"Total Dataset Rows": st.session_state.total_input_count}])
        
        excel_bin = backend_stage3.build_excel_ledger(metrics, df_res, st.session_state.root_negatives)
        st.download_button("Save Multi-Tab Ledger Document", excel_bin, "Negative_Audit_Workbook.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
    if st.button("Return to Metrics Engine Panel"):
        st.session_state.stage = 2
        st.rerun()
