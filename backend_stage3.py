import gspread
from google.oauth2.service_account import Credentials
import streamlit as st

def push_to_google_sheets(cache_key: str, payload: dict) -> str:
    """
    Creates a detailed multi-tab optimization workbook and passes back the public URL.
    """
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    gc = gspread.authorize(creds)
    
    # Create a fresh spreadsheet workbook
    sheet_title = f"Negative Optimization Ledger: {cache_key}"
    spreadsheet = gc.create(sheet_title)
    
    # Share it so that the user can open the link
    # NOTE: In a production environment, you might share with a specific email or make public via link
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
            worksheet = spreadsheet.add_worksheet(title=tab_name[:30], rows="100", cols="20")
            
        # Convert list of dicts to standard rows with headers
        if isinstance(rows, list) and len(rows) > 0 and isinstance(rows[0], dict):
            headers = list(rows[0].keys())
            data_matrix = [headers]
            for r in rows:
                data_matrix.append([str(r.get(h, "")) for h in headers])
            worksheet.update(range_name="A1", values=data_matrix)
            
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}"
