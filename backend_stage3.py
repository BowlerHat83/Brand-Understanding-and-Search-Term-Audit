import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
import streamlit as st

def push_to_google_sheets(cache_key: str, payload: dict) -> str:
    """
    Creates a detailed multi-tab optimization workbook and passes back the public URL.
    Automatically purges sheets older than 5 days from the service account to protect the quota.
    """
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    
    # -------------------------------------------------------------------------
    # 🧼 STORAGE AUTO-PURGE PIPELINE (Fixes Quota Error E005)
    # -------------------------------------------------------------------------
    try:
        # Connect explicitly to the Google Drive API service
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Calculate the cutoff timestamp for 5 days ago
        five_days_ago = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        
        # Look for Google Sheets older than 5 days owned by this account
        query = f"mimeType = 'application/vnd.google-apps.spreadsheet' and modifiedTime < '{five_days_ago}'"
        
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        files_to_delete = results.get('files', [])
        
        # Permanently delete expired spreadsheets to clear up storage space
        for file in files_to_delete:
            drive_service.files().delete(fileId=file['id']).execute()
            
    except Exception as purge_error:
        # Soft-fail so that if the cleanup has an issue, it doesn't break the main app
        pass
    # -------------------------------------------------------------------------

    # Authorize gspread to handle the sheet creation
    gc = gspread.authorize(creds)
    
    # Create a fresh spreadsheet workbook
    sheet_title = f"Negative Optimization Ledger: {cache_key}"
    spreadsheet = gc.create(sheet_title)
    
    # Share it so that the user can open the link
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
