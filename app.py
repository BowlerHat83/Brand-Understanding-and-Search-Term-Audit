import inspect
import asyncio
import pandas as pd
import streamlit as st

# Import processing functions from backend module
from backend_stage2 import (
    classify_terms_batch,
    extract_root_negatives,
    apply_ads_notation,
    is_foreign_script,
)

# ==========================================
# 🛡️ GLOBAL SESSION STATE INITIALIZATION
# ==========================================
if "stage" not in st.session_state:
    st.session_state.stage = 1

if "cache_key" not in st.session_state:
    st.session_state.cache_key = "Default Workspace"

if "locked_rules" not in st.session_state:
    st.session_state.locked_rules = {}

# ==========================================
# 📊 APP STAGE ROUTER FRAMEWORK
# ==========================================

# STAGE 1 ROUTE: Workspace & Rules Setup
if st.session_state.stage == 1:
    st.header("Stage 1: Workspace & Brand Context Setup")
    
    st.info("Configure your brand context baseline rules below before proceeding.")
    
    # Placeholder Stage 1 Form Configuration
    workspace_name = st.text_input("Workspace Name", value=st.session_state.cache_key)
    
    if st.button("Save & Proceed to Stage 2 Audit", type="primary"):
        st.session_state.cache_key = workspace_name
        st.session_state.stage = 2
        st.rerun()

# STAGE 2 ROUTE: Async Matrix Execution Engine
elif st.session_state.stage == 2:
    st.header(f"Stage 2: Audit Engine — Workspace: {st.session_state.cache_key}")
    
    if st.button("⬅️ Back to Stage 1 Setup"):
        st.session_state.stage = 1
        st.rerun()
        
    uploaded_file = st.file_uploader("Upload Search Term Export (CSV Format)", type=["csv"])

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
                    
                    relevant_list, irrelevant_list, review_list, overlooked_list = [], [], [], []
                    api_queue = []
                    
                    for term in search_terms:
                        if is_foreign_script(term):
                            irrelevant_list.append({
                                "Search Term": term, 
                                "Confidence Score": 1.0, 
                                "Reasoning": "Auto-Filter: Non-Latin characters."
                            })
                        else:
                            api_queue.append(term)
                            
                    BATCH_SIZE = 100
                    batches = [api_queue[x:x+BATCH_SIZE] for x in range(0, len(api_queue), BATCH_SIZE)]
                    total_batches = len(batches)
                    completed_batches = 0
                    
                    async def wrapped_task(index, batch, rules, lock):
                        nonlocal completed_batches
                        try:
                            res = await classify_terms_batch(batch, rules)
                            
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
                        rules = st.session_state.get("locked_rules", {})
                        tasks = [wrapped_task(i, b, rules, lock) for i, b in enumerate(batches)]
                        return await asyncio.gather(*tasks, return_exceptions=True)
                    
                    with st.spinner(f"📡 Matrix Engine Active: Dispatching {total_batches} parallel API threads..."):
                        status_lbl.markdown(f"⚡ **Processing Matrix:** Completed `0/{total_batches}` batches... (Remaining: {total_batches})")
                        
                        try:
                            loop = asyncio.get_event_loop()
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            
                        loop_results = loop.run_until_complete(process_all_concurrently())
                    
                    status_lbl.markdown("📝 **Assembling final matrix ledgers...**")
                    for index, res_block in enumerate(loop_results):
                        if isinstance(res_block, Exception):
                            failed_batch = batches[index]
                            for term in failed_batch:
                                overlooked_list.append({
                                    "Search Term": term, 
                                    "Confidence Score": 0.0, 
                                    "Reasoning": f"API Error: {repr(res_block)}"
                                })
                            continue
                            
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
                            failed_batch = batches[index]
                            for term in failed_batch:
                                overlooked_list.append({
                                    "Search Term": term, 
                                    "Confidence Score": 0.0, 
                                    "Reasoning": "Corrupted response block."
                                })
                    
                    protected = st.session_state.get("locked_rules", {}).get("protected_terms", [])
                    irr_phrases = [r["Search Term"] for r in irrelevant_list]
                    saved_phrases = [r["Search Term"] for r in relevant_list] + [r["Search Term"] for r in review_list] + [r["Search Term"] for r in overlooked_list]
                    
                    raw_roots = extract_root_negatives(irr_phrases, saved_phrases, protected)
                    root_payload = [{
                        "Root Word": w, 
                        "Blocked Volume Count": c, 
                        "Ads Notation Match": apply_ads_notation(w, is_exact=False)
                    } for w, c in raw_roots.items()]
                    
                    copy_paste_out = [rn["Ads Notation Match"] for rn in root_payload]
                    for irr in irrelevant_list:
                        copy_paste_out.append(apply_ads_notation(irr["Search Term"], is_exact=False))
                    copy_paste_out = list(set(copy_paste_out))
                    
                    st.session_state.audit_results = {
                        "metrics": {
                            "Total Inputted Terms": total_count, 
                            "Relevant Terms": len(relevant_list), 
                            "Irrelevant Terms": len(irrelevant_list),
                            "Review Queue Terms": len(review_list), 
                            "Potentially Overlooked Terms": len(overlooked_list), 
                            "Extracted Roots Count": len(root_payload)
                        },
                        "relevant": relevant_list, 
                        "irrelevant": irrelevant_list, 
                        "review": review_list, 
                        "overlooked": overlooked_list,
                        "roots": root_payload, 
                        "copy_paste_list": copy_paste_out
                    }
                    status_lbl.empty()
                    st.rerun()
            except Exception as e:
                st.error(f"Execution run crashed: {str(e)}")

    render_execution_engine(uploaded_file)
