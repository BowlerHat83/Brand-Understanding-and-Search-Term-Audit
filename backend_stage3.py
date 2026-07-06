import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
import streamlit as st
import time

def push_to_google_sheets(cache_key: str, payload: dict) -> str:
    """
    Brand New Stage 3 Architecture.
    Generates a secure, multi-tab Google Sheet ledger using fresh credentials.
    Features a built-in 5-day rolling auto-purge retention policy.
    """
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    
    # -------------------------------------------------------------------------
    # 🧼 5-DAY ROLLING AUTO-PURGE RETENTION POLICY
    # -------------------------------------------------------------------------
    try:
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Calculate the strict 5-day cutoff timestamp
        five_days_ago = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        
        # Identify spreadsheets older than 5 days owned by this service account
        query = f"mimeType = 'application/vnd.google-apps.spreadsheet' and modifiedTime < '{five_days_ago}'"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        files_to_delete = results.get('files', [])
        
        # Shred expired ledger sheets to dynamically reclaim storage space
        for file in files_to_delete:
            drive_service.files().delete(fileId=file['id']).execute()
            
    except Exception as maintenance_error:
        # Soft-fail so code safely proceeds if Drive API hasn't finished propagation
        pass

    # -------------------------------------------------------------------------
    # 📊 WORKSHEET COMPILATION ENGINE
    # -------------------------------------------------------------------------
    gc = gspread.authorize(creds)
    
    # Unique timestamp prevents collision or indexing confusion
    sheet_title = f"Optimization Ledger ({cache_key}) - {int(time.time())}"
    spreadsheet = gc.create(sheet_title)
    
    # Authorize anonymous link viewing so the frontend user can access it instantly
    spreadsheet.share('', perm_type='anyone', role='viewer')
    
    first_tab = True
    for tab_name, rows in payload.items():
        if not rows:
            continue
            
        if first_tab:
            worksheet = spreadsheet.sheet1
            worksheet.update_title(tab_name[:30]) # Bound by Google's 30-char tab limit
            first_tab = False
        else:
            worksheet = spreadsheet.add_worksheet(title=tab_name[:30], rows="100", cols="20")
            
        if isinstance(rows, list) and len(rows) > 0 and isinstance(rows[0], dict):
            headers = list(rows[0].keys())
            data_matrix = [headers]
            for r in rows:
                data_matrix.append([str(r.get(h, "")) for h in headers])
                
            # Modern, version-proof update layout
            worksheet.update(values=data_matrix, range_name="A1")

    return f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}"

# --- ADD THIS TO THE BOTTOM OF YOUR FILE TO FIX THE IMPORT ERROR ---

def update_brand_profile_cache(cache_key: str, profile_data: dict) -> bool:
    """
    Saves or updates the processed brand profile data in Streamlit's 
    session state cache to prevent redundant Google Sheets reads.
    """
    try:
        if 'brand_profile_cache' not in st.session_state:
            st.session_state['brand_profile_cache'] = {}
            
        st.session_state['brand_profile_cache'][cache_key] = {
            'data': profile_data,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        return True
    except Exception as e:
        st.warning(f"Cache Sync Warning: {str(e)}")
        return False



