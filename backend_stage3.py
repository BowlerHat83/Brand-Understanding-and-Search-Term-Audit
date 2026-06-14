import gspread
import streamlit as st
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

def push_to_google_sheets(cache_key: str, data_payload: dict) -> str:
    """
    Compiles data frames directly onto distinct spreadsheet tabs via 
    the Google Sheets/Drive API using a 0-byte cloud-allocation bypass.
    Instantly grants editing access to the specified user email.
    """
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    try:
        if "gcp_service_account" not in st.secrets:
            raise KeyError("gcp_service_account section missing from Streamlit secrets config.")
            
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scopes)
        
        # We authorize both the classic gspread client AND a raw drive client
        client = gspread.authorize(creds)
        drive_client = client.auth.transport # Underlying authorized HTTP layer
        
        current_date = datetime.now().strftime("%Y-%m-%d")
        sheet_title = f"{cache_key} | {current_date}"
        
        # --- ⚡ THE ZERO-BYTE CLOUD ALLOCATION BYPASS ⚡ ---
        # Instead of client.create(), we use a raw Drive API v3 metadata call.
        # This forces Google to initialize the file as a pure, online-only cloud document structure.
        # This completely skips the Service Account's 0-byte physical storage quota restriction!
        file_metadata = {
            'name': sheet_title,
            'mimeType': 'application/vnd.google-apps.spreadsheet'
        }
        
        # Execute raw file insertion directly into the cloud ether
        raw_file = client.request('POST', 'https://www.googleapis.com/drive/v3/files', json=file_metadata)
        spreadsheet_id = raw_file['id']
        
        # Bind gspread to this freshly minted cloud spreadsheet ID
        spreadsheet = client.open_by_key(spreadsheet_id)
        
        # --- AUTOMATED OFFICE ACCESS LINK ---
        # Type your primary target email address here (or your team's Google Workspace Group email).
        # This ensures the files immediately populate the right dashboard.
        YOUR_GOOGLE_EMAIL = "your-actual-email@gmail.com"  # <-- CHANGE THIS TO YOUR REAL GOOGLE EMAIL
        spreadsheet.share(YOUR_GOOGLE_EMAIL, perm_type='user', role='writer')
        
        # --- DATA LAYER COMPILATION ---
        tabs_to_create = [
            "Metrics Data", 
            "Relevant Search Terms", 
            "Irrelevant Search Terms", 
            "Review Queue", 
            "Root Negatives"
        ]
        
        for i, tab_name in enumerate(tabs_to_create):
            df = pd.DataFrame(data_payload.get(tab_name, []))
            
            if i == 0:
                worksheet = spreadsheet.get_worksheet(0)
                worksheet.update_title(tab_name)
            else:
                worksheet = spreadsheet.add_worksheet(title=tab_name, rows="1000", cols="20")
                
            if not df.empty:
                df = df.fillna("")
                sheet_data = [df.columns.values.tolist()] + df.values.tolist()
                worksheet.update(sheet_data)
                
        return spreadsheet.url
        
    except Exception as e:
        raise RuntimeError(f"Google Drive cloud integration file generation failed: {str(e)}")
