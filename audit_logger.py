import io
import pandas as pd

def generate_deep_dive_workbook(audit_results: dict) -> io.BytesIO:
    """
    Takes the master output payload from Stage 2 and structures it into
    a multi-tab spreadsheet buffer ready for native Google Sheets / Excel download.
    """
    # Create an in-memory binary stream so we don't clog up the server with physical files
    output_buffer = io.BytesIO()
    
    # Extract the raw records passed from the AI batch evaluation loops
    # (Note: For this to work seamlessly, we will slightly update Stage 2's return dictionary 
    # to pass the raw objects containing the reasoning and confidence fields)
    relevant_data = audit_results.get("raw_classified_records", {}).get("relevant", [])
    review_data = audit_results.get("raw_classified_records", {}).get("review", [])
    irrelevant_data = audit_results.get("raw_classified_records", {}).get("irrelevant", [])
    roots_data = audit_results.get("raw_classified_records", {}).get("roots_summary", [])

    # Convert the raw lists of dicts into standardized pandas DataFrames
    df_relevant = pd.DataFrame(relevant_data, columns=["Search Term", "Reasoning", "Confidence Score"])
    df_review = pd.DataFrame(review_data, columns=["Search Term", "Reasoning", "Confidence Score"])
    df_irrelevant = pd.DataFrame(irrelevant_data, columns=["Search Term", "Reasoning", "Confidence Score"])
    
    # Tab 4 explicitly excludes confidence scores, focusing purely on root frequencies
    df_roots = pd.DataFrame(roots_data, columns=["Isolated Root Word", "Frequency Count"])

    # Initialize the Excel writer engine using the in-memory buffer
    with pd.ExcelWriter(output_buffer, engine="openpyxl") as writer:
        df_relevant.to_excel(writer, sheet_name="1. Relevant Terms", index=False)
        df_review.to_excel(writer, sheet_name="2. Review Queue", index=False)
        df_irrelevant.to_excel(writer, sheet_name="3. Irrelevant Terms", index=False)
        df_roots.to_excel(writer, sheet_name="4. Root Negatives", index=False)
        
    # Reset the buffer pointer to the beginning so Streamlit can read it cleanly
    output_buffer.seek(0)
    return output_buffer
