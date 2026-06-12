import streamlit as st
import pandas as pd
import json
import os

# Import our brand new segmented backend files
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

# --- STAGE 1 ---
if st.session_state.stage == 1:
    st.title("🛡️ Stage 1: Brand Audit")
    cached_profiles = ["Create New"] + [f.replace(".json", "") for f in os.listdir(CACHE_DIR) if f.endswith(".json")]
    selected_profile = st.selectbox("Select Profile", cached_profiles)
    
    if selected_profile != "Create New":
        if st.button("Load & Continue"):
            with open(os.path.join(CACHE_DIR, f"{selected_profile}.json"), "r") as f:
                st.session_state.locked_truth = json.load(f)
            st.session_state.stage = 2
            st.rerun()
    else:
        brand_name = st.text_input("Brand Name")
        core_offering = st.text_input("Core Offering")
        landing_page = st.text_input("Landing Page Link")
        
        if st.button("Launch Brand Understanding Audit"):
            if not brand_name: st.error("🚨 ERR_AUTH_01: Missing Brand Name.")
            elif not core_offering: st.error("🚨 ERR_AUTH_02: Missing Core Offering.")
            elif not landing_page: st.error("🚨 ERR_AUTH_03: Missing Landing Page Link.")
            else:
                progress = st.progress(30)
                # Calling Stage 1 Backend File
                res = backend_stage1.analyze_brand_profile(brand_name, core_offering, landing_page)
                progress.progress(100)
                if "error" in res:
                    st.error(res["error"])
                else:
                    st.session_state.brand_understanding = res
                    st.session_state.current_brand_name = brand_name
                    st.session_state.current_core_offering = core_offering

        if st.session_state.brand_understanding:
            st.markdown("### ✍️ Refine Knowledge Profile")
            bv = st.data_editor(st.session_state.brand_understanding["brand_variants"], num_rows="dynamic", key="ebv")
            cb = st.data_editor(st.session_state.brand_understanding["competitor_brands"], num_rows="dynamic", key="ecb")
            pt = st.data_editor(st.session_state.brand_understanding["protected_terms"], num_rows="dynamic", key="ept")
            ni = st.data_editor(st.session_state.brand_understanding["irrelevant_niches"], num_rows="dynamic", key="eni")
            
            if st.button("Confirm & Lock Base Truth"):
                final_truth = {"brand_variants": bv, "competitor_brands": cb, "protected_terms": pt, "irrelevant_niches": ni}
                name = f"{st.session_state.current_brand_name} | {st.session_state.current_core_offering}".replace("/", "-")
                with open(os.path.join(CACHE_DIR, f"{name}.json"), "w") as f:
                    json.dump(final_truth, f)
                st.session_state.locked_truth = final_truth
                st.session_state.stage = 2
                st.rerun()

# --- STAGE 2 ---
elif st.session_state.stage == 2:
    st.title("🔍 Stage 2: Search Terms Classification")
    uploaded_file = st.file_uploader("Upload Search Terms CSV", type=["csv"])
    
    if st.button("Launch Search Terms Audit"):
        if not uploaded_file:
            st.error("🚨 ERR_DATA_01: Missing Uploaded CSV File.")
        else:
            df_input = pd.read_csv(uploaded_file)
            col = [c for c in df_input.columns if 'term' in c.lower() or 'query' in c.lower()][0]
            raw_terms = df_input[col].dropna().astype(str).unique().tolist()
            
            progress = st.progress(0)
            all_results = []
            batch_size = 150
            
            for i in range(0, len(raw_terms), batch_size):
                progress.progress(int((i / len(raw_terms)) * 100))
                # Calling Stage 2 Backend File
                batch_res = backend_stage2.classify_search_terms_batch(raw_terms[i:i+batch_size], st.session_state.locked_truth)
                all_results.extend(batch_res)
                
            progress.progress(100)
            df_classified = pd.DataFrame(all_results)
            
            if len(raw_terms) != len(df_classified):
                st.error("🚨 ERR_PIPELINE_MISMATCH: Row discrepancies detected.")
                
            st.session_state.root_negatives = backend_stage2.calculate_root_negatives(df_classified)
            st.session_state.classification_results = df_classified
            st.session_state.total_input_count = len(raw_terms)

    if st.session_state.classification_results is not None:
        df_res = st.session_state.classification_results
        st.metric("Total Ingested", st.session_state.total_input_count)
        
        t1, t2 = st.columns(2)
        with t1:
            st.subheader("Review Queue")
            st.dataframe(df_res[df_res['classification'] == 'review'][['term', 'confidence_score']])
        with t2:
            st.subheader("Direct Copy Negative Output")
            formatted = backend_stage2.generate_google_ads_notation(df_res, st.session_state.root_negatives)
            st.code("\n".join(formatted), language="text")
            
        if st.button("🚀 Proceed to Ledger Download"):
            st.session_state.stage = 3
            st.rerun()
        if st.button("🔄 Clear and Reset Session"):
            st.session_state.clear()
            st.rerun()

# --- STAGE 3 ---
elif st.session_state.stage == 3:
    st.title("🗂️ Stage 3: Ledger Distribution Layout")
    
    if st.button("📥 Build & Download Excel Workbook"):
        df_res = st.session_state.classification_results
        metrics = pd.DataFrame([{"Total Rows": st.session_state.total_input_count}])
        
        # Calling Stage 3 Backend File
        excel_bin = backend_stage3.build_excel_ledger(metrics, df_res, st.session_state.root_negatives)
        
        st.download_button("Click to Save File", excel_bin, "negative_audit.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
    if st.button("⬅️ Back to Metrics view"):
        st.session_state.stage = 2
        st.rerun()
