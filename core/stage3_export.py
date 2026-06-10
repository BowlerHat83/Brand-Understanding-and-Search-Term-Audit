import pandas as pd
from datetime import datetime
from pathlib import Path


# -----------------------------
# OUTPUT DIR
# -----------------------------
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


# -----------------------------
# MAIN EXPORT FUNCTION
# -----------------------------
def export_to_excel(stage2_results: list, root_negatives: list = None) -> str:
    """
    Converts Stage 2 output into a structured Excel workbook.
    """

    if root_negatives is None:
        root_negatives = []

    # -----------------------------
    # DATAFRAME BUILD
    # -----------------------------
    df = pd.DataFrame(stage2_results)

    if df.empty:
        raise ValueError("No Stage 2 results to export")

    # -----------------------------
    # SPLIT SHEETS
    # -----------------------------
    relevant_df = df[df["classification"] == "relevant"]
    irrelevant_df = df[df["classification"] == "irrelevant"]
    review_df = df[df["classification"] == "review"]

    # low confidence rule (safety net)
    low_confidence_df = df[df["confidence"] < 0.7]

    # -----------------------------
    # FILE NAME
    # -----------------------------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = OUTPUT_DIR / f"search_audit_{timestamp}.xlsx"

    # -----------------------------
    # WRITE EXCEL
    # -----------------------------
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:

        relevant_df.to_excel(writer, sheet_name="Relevant Terms", index=False)
        review_df.to_excel(writer, sheet_name="Review Queue", index=False)
        irrelevant_df.to_excel(writer, sheet_name="Irrelevant Terms", index=False)
        low_confidence_df.to_excel(writer, sheet_name="Low Confidence", index=False)

        # -----------------------------
        # ROOT NEGATIVES SHEET
        # -----------------------------
        pd.DataFrame({
            "root_negative_terms": root_negatives
        }).to_excel(writer, sheet_name="Root Negatives", index=False)

        # -----------------------------
        # SUMMARY SHEET
        # -----------------------------
        summary = pd.DataFrame([{
            "total_terms": len(df),
            "relevant": len(relevant_df),
            "irrelevant": len(irrelevant_df),
            "review": len(review_df),
            "low_confidence": len(low_confidence_df),
            "generated_at": timestamp
        }])

        summary.to_excel(writer, sheet_name="Summary", index=False)

    return str(file_path)
