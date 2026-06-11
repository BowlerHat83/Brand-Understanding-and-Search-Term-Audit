import pandas as pd
from datetime import datetime
from pathlib import Path


# =========================================================
# OUTPUT DIRECTORY
# =========================================================
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


# =========================================================
# MAIN EXPORT FUNCTION
# =========================================================
def export_to_excel(stage2_output: dict) -> str:

    results = stage2_output["results"]
    relevant = stage2_output["relevant"]
    irrelevant = stage2_output["irrelevant"]
    review = stage2_output["review"]
    root_negatives = stage2_output["root_negatives"]

    total_input = len(results)

    # =====================================================
    # DATAFRAME BUILD (NORMALISED)
    # =====================================================
    df_relevant = pd.DataFrame([
        {
            "term": r["term"],
            "confidence": r.get("confidence", 0.0)
        }
        for r in relevant
    ])

    df_review = pd.DataFrame([
        {
            "term": r["term"],
            "confidence": r.get("confidence", 0.0)
        }
        for r in review
    ])

    df_irrelevant = pd.DataFrame([
        {
            "term": r["term"],
            "confidence": r.get("confidence", 0.0),
            "reason": (r.get("reason", "")[:5] if r.get("reason") else "")
        }
        for r in irrelevant
    ])

    df_roots = pd.DataFrame({
        "root_negative_terms": root_negatives
    })

    # =====================================================
    # ERROR 001 CHECK
    # =====================================================
    integrity_ok = (
        len(df_relevant) + len(df_irrelevant) + len(df_review)
    ) == total_input

    # =====================================================
    # SUMMARY SHEET
    # =====================================================
    summary = pd.DataFrame([{
        "total_terms": total_input,
        "relevant": len(df_relevant),
        "irrelevant": len(df_irrelevant),
        "review": len(df_review),
        "root_negatives": len(root_negatives),
        "error_001_status": "PASS" if integrity_ok else "FAIL",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }])

    # =====================================================
    # FILE OUTPUT
    # =====================================================
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = OUTPUT_DIR / f"ppc_audit_{timestamp}.xlsx"

    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:

        summary.to_excel(writer, sheet_name="Summary", index=False)

        df_relevant.to_excel(writer, sheet_name="Relevant Terms", index=False)
        df_irrelevant.to_excel(writer, sheet_name="Irrelevant Terms", index=False)
        df_review.to_excel(writer, sheet_name="Review Queue", index=False)

        df_roots.to_excel(writer, sheet_name="Root Negatives", index=False)

    return str(file_path)
