import re
import json
import inspect
import asyncio
from collections import Counter
import google.generativeai as genai
import streamlit as st
import pandas as pd

# ==========================================
# ⚙️ GLOBAL BACKEND API ENGINE
# ==========================================

# Initialize global rate-limiting gatekeeper (Allows max 5 concurrent API calls)
API_SEMAPHORE = asyncio.Semaphore(5)

async def classify_terms_batch(terms: list, brand_profile: dict) -> list:
    """
    Native Asynchronous batch classification engine.
    Regulated via an internal asyncio.Semaphore to completely eliminate 429 TooManyRequests loops
    while maintaining peak concurrent parallel processing speed.
    """
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    # Model string updated to stable Gemini 2.5 Flash
    model = genai.GenerativeModel('gemini-2.5-flash')
    rules_context = json.dumps(brand_profile, indent=2)
    
    prompt = f"""
    You are a highly defensive, ultra-conservative Google Ads Negative Keyword Auditor.
    Your primary directive is to protect ad spend by aggressively weeding out low-intent, ambiguous, or borderline search terms.

    CORE AUDITING IDEOLOGY (GUILTY UNTIL PROVEN INNOCENT):
    - Every search term is considered IRRELEVANT or requires REVIEW by default.
    - A term is NEVER 'relevant' simply because it is vaguely or tangentially related to the industry.
    - A term must actively PROVE its strict commercial intent and clear alignment with core offerings to be marked 'relevant'.

    CRITICAL CLASSIFICATION BOUNDARIES:
    1. 'relevant' -> Use ONLY if the term shows explicit intent to buy, hire, or use core offerings, AND it contains zero educational, research, or casual intent signals.
    2. 'irrelevant' -> Use if it matches competitor targets, explicit exclusion flags, or falls completely outside target offerings.
    3. 'review' -> Use if you are even 1% uncertain, if it lacks a clear intent modifier, or contains mixed signals.

    Active Brand Rules Context Baseline:
    {rules_context}
    
    Terms to classify:
    {json.dumps(terms)}
    
    Respond STRICTLY with a valid JSON array of objects. Each object must have these exact keys:
    - "search_term": (string matching the input exactly)
    - "classification": (strictly choose one: "relevant", "irrelevant", or "review")
    - "confidence": (float between 0.00 and 1.00)
    - "reason": (string)
    
    CRITICAL SPEED RULE FOR THE 'reason' VALUE:
    - If confidence is 0.80 or higher, you MUST set "reason": "" (an empty string). Do not write text for obvious classifications.
    - Only if confidence is LESS than 0.80, provide a short explanation of 5 words or less.
    """
    
    # Use the semaphore to regulate access to the network request block
    async with API_SEMAPHORE:
        # Extended retry mechanism to handle Google 503 capacity issues and 429 rate limits
        max_attempts = 4
        for attempt in range(max_attempts):
            try:
                # Use the native async generation function to avoid main thread lockups
                response = await model.generate_content_async(
                    prompt,
                    generation_config={
                        "response_mime_type": "application/json",
                        "temperature": 0.1
                    }
                )
                
                clean_text = response.text.strip()
                if clean_text.startswith("```"):
                    lines = clean_text.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    clean_text = "\n".join(lines).strip()
                    
                return json.loads(clean_text)
                
            except Exception as e:
                error_msg = str(e)
                # Catch both Google 503 capacity overloads and 429 rate limits
                if "503" in error_msg or "429" in error_msg or "Quota" in error_msg or "Unavailable" in error_msg:
                    if attempt < max_attempts - 1:
                        # Exponential backoff: sleep 2s, 4s, 6s between retries
                        await asyncio.sleep(2.0 * (attempt + 1))
                        continue
                
                # Fallback ledger generation preserving full diagnostic string
                return [{"search_term": t, "classification": "review", "confidence": 0.5, "reason": f"Err: {repr(e)[:40]}"} for t in terms]
        
        return [{"search_term": t, "classification": "review", "confidence": 0.5, "reason": "Err: Server Capacity Exceeded"} for t in terms]

def extract_root_negatives(irrelevant_phrases: list, saved_phrases: list, protected_list: list) -> dict:
    irr_words = []
    for phrase in irrelevant_phrases:
        irr_words.extend(re.findall(r'\b\w+\b', phrase.lower()))
        
    saved_words = set()
    for phrase in saved_phrases:
        saved_words.update(re.findall(r'\b\w+\b', phrase.lower()))
        
    for phrase in protected_list:
        saved_words.update(re.findall(r'\b\w+\b', phrase.lower()))
        
    counts = Counter([w for w in irr_words if w not in saved_words and len(w) > 2])
    return {word: count for word, count in counts.items() if count >= 2}

def apply_ads_notation(term: str, is_exact: bool = False) -> str:
    clean_term = term.strip().lower().strip("[]\"'")
    if is_exact:
        return f"[{clean_term}]"
    else:
        return f'"{clean_term}"'

def is_foreign_script(text: str) -> bool:
    """Helper function to filter non-Latin script query inputs."""
    return bool(re.search(r'[\u0E00-\u0E7F\u0400-\u04FF\u0600-\u06FF\u0590-\u05FF]', text))


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
                    
                    async def wrapped_task(index, batch, rules, lock):
                        nonlocal completed_batches
                        try:
                            # Direct mapping to correct classify_terms_batch backend signature
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
                    
                    # 3. Streamlit Spinner Visual Trust Gateway
                    with st.spinner(f"📡 Matrix Engine Active: Dispatching {total_batches} parallel API threads..."):
                        status_lbl.markdown(f"⚡ **Processing Matrix:** Completed `0/{total_batches}` batches... (Remaining: {total_batches})")
                        
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
                                overlooked_list.append({"Search Term": term, "Confidence Score": 0.0, "Reasoning": "Corrupted response block."})
                    
                    # 5. Final Core Analytics & Negative Optimization Extraction Build
                    protected = st.session_state.get("locked_rules", {}).get("protected_terms", [])
                    irr_phrases = [r["Search Term"] for r in irrelevant_list]
                    saved_phrases = [r["Search Term"] for r in relevant_list] + [r["Search Term"] for r in review_list] + [r["Search Term"] for r in overlooked_list]
                    
                    raw_roots = extract_root_negatives(irr_phrases, saved_phrases, protected)
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

    render_execution_engine(uploaded_file)
