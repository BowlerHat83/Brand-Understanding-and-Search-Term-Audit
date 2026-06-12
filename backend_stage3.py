import io
import pandas as pd

def build_excel_ledger(df_metrics, df_classified, root_negatives_list):
    """Compiles a memory-buffered multi-tab spreadsheet to return straight to the client UI."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_metrics.to_excel(writer, sheet_name='Metrics Data', index=False)
        
        df_classified[df_classified['classification'] == 'relevant'][['term', 'confidence_score']].to_excel(writer, sheet_name='Relevant Terms', index=False)
        
        df_classified[df_classified['classification'] == 'irrelevant'][['term', 'confidence_score', 'reasoning']].to_excel(writer, sheet_name='Irrelevant Terms', index=False)
        
        df_classified[df_classified['classification'] == 'review'][['term', 'confidence_score']].to_excel(writer, sheet_name='Review Queue', index=False)
        
        df_roots = pd.DataFrame(root_negatives_list)[['root_negative', 'blocked_count']] if root_negatives_list else pd.DataFrame(columns=['root_negative', 'blocked_count'])
        df_roots.to_excel(writer, sheet_name='Root Negatives', index=False)
        
    return output.getvalue()
