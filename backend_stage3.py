import gspread
import streamlit as st
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

def push_to_google_sheets(cache_key: str, data_payload: dict) -> str:
    """
    Overwrites a shared master spreadsheet across the office,
    completely bypassing the service account storage creation quotas.
    """
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    try:
        if "gcp_service_account" not in st.secrets:
            raise KeyError("gcp_service_account section missing from Streamlit secrets config.")
            
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scopes)
        client = gspread.authorize(creds)
        
        # --- 🎯 THE BULLETPROOF MASTER TEMPLATE BYPASS ---
        # Paste your manually created Google Sheet ID right here:
        MASTER_SPREADSHEET_ID = "1om-Du-zmqd3dy-KtUxiMVWAYLhVVGqZha9bpuI0ZRNs"
        
        # Open the shared office asset directly
        spreadsheet = client.open_by_key(MASTER_SPREADSHEET_ID)
        
        tabs_to_update = [
            "Metrics Data", 
            "Relevant Search Terms", 
            "Irrelevant Search Terms", 
            "Review Queue", 
            "Root Negatives"
        ]
        
        for tab_name in tabs_to_update:
            df = pd.DataFrame(data_payload.get(tab_name, []))
            
            # Try to grab the tab if it exists, otherwise build it dynamically
            try:
                worksheet = spreadsheet.worksheet(tab_name)
                worksheet.clear() # Wipe old audit run clean
            except gspread.exceptions.WorksheetNotFound:
                worksheet = spreadsheet.add_worksheet(title=tab_name, rows="1000", cols="20")
                
            if not df.empty:
                df = df.fillna("")
                sheet_data = [df.columns.values.tolist()] + df.values.tolist()
                worksheet.update(sheet_data)
                
        return spreadsheet.url
        
    except Exception as e:
        raise RuntimeError(f"Google Drive cloud integration file generation failed: {str(e)}")
