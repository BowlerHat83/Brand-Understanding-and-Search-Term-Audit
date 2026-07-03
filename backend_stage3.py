import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import time

def push_to_google_sheets(cache_key: str, payload: dict) -> str:
    """
    Creates a completely fresh, unlinked multi-tab optimization workbook.
    Uses a unique epoch timestamp to guarantee it never collides with 
    any locked or shared ghost files on the system.
    """
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    gc = gspread.authorize(creds)
    
    # -------------------------------------------------------------------------
    # 🆕 FRESH SLATE GENERATION
    # -------------------------------------------------------------------------
    # Appending a unique timestamp ensures Google treats this as a brand new asset,
    # completely detached from any past files that threw permission errors.
    unique_id = int(time.time())
    sheet_title = f"New Optimization Ledger ({cache_key}) - {unique_id}"
    
    # Create the fresh spreadsheet workbook
    spreadsheet = gc.create(sheet_title)
    
    # Share it globally via link so you can open it instantly from Streamlit
    spreadsheet.share('', perm_type='anyone', role='viewer')
    
    # Populate Tabs based on the incoming dictionary payload keys
    first_tab = True
    for tab_name, rows in payload.items():
        if not rows:
            continue
            
        if first_tab:
            worksheet = spreadsheet.sheet1
            worksheet.update_title(tab_name[:30]) # Google Sheets limits tab titles to 30 chars
            first_tab = False
        else:
            # Create fresh worksheets with standard dimensions
            worksheet = spreadsheet.add_worksheet(title=tab_name[:30], rows="100", cols="20")
            
        # Convert list of dicts to standard rows with headers
        if isinstance(rows, list) and len(rows) > 0 and isinstance(rows[0], dict):
            headers = list(rows[0].keys())
            data_matrix = [headers]
            for r in rows:
                data_matrix.append([str(r.get(h, "")) for h in headers])
                
            # Version-proof update syntax using named parameters
            worksheet.update(values=data_matrix, range_name="A1")
            
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}"
