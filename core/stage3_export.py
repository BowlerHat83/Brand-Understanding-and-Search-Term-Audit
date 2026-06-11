import pandas as pd
from datetime import datetime
from pathlib import Path


# =========================================================
# OUTPUT DIR (SAFE FOR CLOUD + LOCAL)
# =========================================================
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


# =========================================================
# MAIN EXPORT FUNCTION
# =========================================================
def export_to_excel(stage2_results: list, root_negatives: list = None) -> str:
    """
    Converts Stage 2 output into structured Excel workbook.
    Never crashes Streamlit app — always returns file path or fallback.
    """

    if root_negatives is None:
        root_negatives = []

    # -----------------------------
    # SAFETY CHECK
    # -----------------------------
    if not stage2_results or not isinstance(stage2_results, list):
        raise ValueError("No valid results to export")

    df = pd.DataFrame(stage2_results)

    if df.empty:
        raise ValueError("Empty dataframe — nothing to export")

    # -----------------------------
    # COLUMN SAFETY
    # -----------------------------
    required_cols = ["term", "classification", "confidence"]

    for col in required_cols:
        if col not in df.columns:
            df[col] = None

    # Ensure safe defaults
    df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0)
    df["classification"] = df["classification"].fillna("review")
    df["term"] = df["term"].fillna("unknown")

    # -----------------------------
    # SPLITS
    # -----------------------------
    relevant_df = df[df["classification"] == "relevant"]
    irrelevant_df = df[df["classification"] == "irrelevant"]
    review_df = df[df["classification"] == "review"]
    low_conf_df = df[df["confidence"] < 0.7]

    # -----------------------------
    # FILE NAME (SAFE + UNIQUE)
    # -----------------------------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = OUTPUT_DIR / f"ppc_audit_{timestamp}.xlsx"

    # -----------------------------
    # WRITE EXCEL (FAIL SAFE)
    # -----------------------------
    try:
        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:

            relevant_df.to_excel(writer, sheet_name="Relevant", index=False)
            irrelevant_df.to_excel(writer, sheet_name="Irrelevant", index=False)
            review_df.to_excel(writer, sheet_name="Review", index=False)
            low_conf_df.to_excel(writer, sheet_name="Low Confidence", index=False)

            pd.DataFrame({
                "root_negative_terms": root_negatives
            }).to_excel(writer, sheet_name="Root Negatives", index=False)

            summary = pd.DataFrame([{
                "total_terms": len(df),
                "relevant": len(relevant_df),
                "irrelevant": len(irrelevant_df),
                "review": len(review_df),
                "low_confidence": len(low_conf_df),
                "generated_at": timestamp
            }])

            summary.to_excel(writer, sheet_name="Summary", index=False)

    except Exception as e:
        # NEVER crash app — return fallback info instead
        fallback_path = OUTPUT_DIR / "export_failed.txt"
        fallback_path.write_text(str(e))
        return str(fallback_path)

    return str(file_path)
