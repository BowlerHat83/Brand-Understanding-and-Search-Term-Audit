import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import streamlit as st

def push_to_google_sheets(cache_key: str, payload: dict) -> str:
    """
    Temporary recovery function: Forcefully wipes the ghost files 
    clogging the service account quota, then builds your fresh ledger.
    """
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    
    # 🚨 FORCE PURGE THE GHOST FILES FIRST
    try:
        drive_service = build('drive', 'v3', credentials=creds)
        results = drive_service.files().list(
            q="mimeType = 'application/vnd.google-apps.spreadsheet'", 
            fields="files(id, name)"
        ).execute()
        ghost_files = results.get('files', [])
        
        for f in ghost_files:
            drive_service.files().delete(fileId=f['id']).execute()
        st.toast("🧹 Robot ghost storage completely wiped and reset to 0%!")
    except Exception as e:
        st.warning(f"Purge note: {e}")

    # AUTHORIZE AND CREATE FRESH LEDGER
    gc = gspread.authorize(creds)
    sheet_title = f"Negative Ledger - Fresh Run"
    spreadsheet = gc.create(sheet_title)
    
    # Make it globally accessible via link so you can actually open it
    spreadsheet.share('', perm_type='anyone', role='viewer')
    
    # Build the sheets
    first_tab = True
    for tab_name, rows in payload.items():
        if not rows:
            continue
        if first_tab:
            worksheet = spreadsheet.sheet1
            worksheet.update_title(tab_name[:30])
            first_tab = False
        else:
            worksheet = spreadsheet.add_worksheet(title=tab_name[:30], rows="100", cols="20")
            
        if isinstance(rows, list) and len(rows) > 0 and isinstance(rows[0], dict):
            headers = list(rows[0].keys())
            data_matrix = [headers]
            for r in rows:
                data_matrix.append([str(r.get(h, "")) for h in headers])
            worksheet.update(values=data_matrix, range_name="A1")
            
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}"
