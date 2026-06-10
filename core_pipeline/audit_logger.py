import io
import pandas as pd


STANDARD_COLS = ["Search Term", "Reasoning", "Confidence Score"]
ROOT_COLS = ["Isolated Root Word", "Frequency Count"]


def _make_df(data, cols, fill_value=""):
    """
    Fast, safe dataframe builder with consistent schema enforcement.
    """
    df = pd.DataFrame(data or [], columns=cols)

    if not df.empty:
        df = df.reindex(columns=cols, fill_value=fill_value)

    return df


def generate_deep_dive_workbook(audit_results: dict) -> io.BytesIO:
    """
    Converts audit output into a multi-sheet Excel workbook.
    """

    output_buffer = io.BytesIO()
    raw = audit_results.get("raw_classified_records", {})

    # -----------------------------
    # Build DataFrames (clean + consistent)
    # -----------------------------
    df_relevant = _make_df(raw.get("relevant"), STANDARD_COLS)
    df_review = _make_df(raw.get("review"), STANDARD_COLS)
    df_irrelevant = _make_df(raw.get("irrelevant"), STANDARD_COLS)
    df_roots = _make_df(raw.get("roots_summary"), ROOT_COLS, fill_value=0)

    # -----------------------------
    # Write Excel
    # -----------------------------
    with pd.ExcelWriter(output_buffer, engine="openpyxl") as writer:
        df_relevant.to_excel(writer, sheet_name="1. Relevant Terms", index=False)
        df_review.to_excel(writer, sheet_name="2. Review Queue", index=False)
        df_irrelevant.to_excel(writer, sheet_name="3. Irrelevant Terms", index=False)
        df_roots.to_excel(writer, sheet_name="4. Root Negatives", index=False)

    output_buffer.seek(0)
    return output_buffer
