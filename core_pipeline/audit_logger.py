import io
import pandas as pd

def generate_deep_dive_workbook(audit_results: dict) -> io.BytesIO:
    """
    Takes the master output payload from Stage 2 and structures it into
    a multi-tab spreadsheet buffer ready for native Google Sheets / Excel download.
    """
    output_buffer = io.BytesIO()
    raw_records = audit_results.get("raw_classified_records", {})
    
    relevant_data = raw_records.get("relevant", [])
    review_data = raw_records.get("review", [])
    irrelevant_data = raw_records.get("irrelevant", [])
    roots_data = raw_records.get("roots_summary", [])

    standard_cols = ["Search Term", "Reasoning", "Confidence Score"]
    root_cols = ["Isolated Root Word", "Frequency Count"]

    df_relevant = pd.DataFrame(relevant_data) if relevant_data else pd.DataFrame(columns=standard_cols)
    df_review = pd.DataFrame(review_data) if review_data else pd.DataFrame(columns=standard_cols)
    df_irrelevant = pd.DataFrame(irrelevant_data) if irrelevant_data else pd.DataFrame(columns=standard_cols)
    df_roots = pd.DataFrame(roots_data) if roots_data else pd.DataFrame(columns=root_cols)

    if not df_relevant.empty:  df_relevant = df_relevant.reindex(columns=standard_cols, fill_value="")
    if not df_review.empty:    df_review = df_review.reindex(columns=standard_cols, fill_value="")
    if not df_irrelevant.empty: df_irrelevant = df_irrelevant.reindex(columns=standard_cols, fill_value="")
    if not df_roots.empty:       df_roots = df_roots.reindex(columns=root_cols, fill_value=0)

    try:
        with pd.ExcelWriter(output_buffer, engine="openpyxl") as writer:
            df_relevant.to_excel(writer, sheet_name="1. Relevant Terms", index=False)
            df_review.to_excel(writer, sheet_name="2. Review Queue", index=False)
            df_irrelevant.to_excel(writer, sheet_name="3. Irrelevant Terms", index=False)
            df_roots.to_excel(writer, sheet_name="4. Root Negatives", index=False)
    except Exception as excel_err:
        raise excel_err
        
    output_buffer.seek(0)
    return output_buffer
