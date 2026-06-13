import gspread
import streamlit as st
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

def push_to_google_sheets(cache_key: str, data_payload: dict) -> str:
    """
    Compiles structured data frames directly onto distinct spreadsheet tabs via 
    the Google Sheets API using credentials stored in Streamlit Cloud Secrets.
    Instantly shares ownership/editing access with the specified human email.
    Returns the live editable workspace direct access URL string.
    """
    # Define the security scopes required to create and write files in Google Drive
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    try:
        # Pull the credentials dictionary directly from Streamlit's secure cloud storage
        if "gcp_service_account" not in st.secrets:
            raise KeyError("gcp_service_account section missing from Streamlit secrets config.")
            
        creds_dict = dict(st.secrets["gcp_service_account"])
        
        # Authenticate using the in-memory dictionary payload
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scopes)
        client = gspread.authorize(creds)
        
        # Format filename convention: Brand Name | Core Offering | YYYY-MM-DD
        current_date = datetime.now().strftime("%Y-%m-%d")
        sheet_title = f"{cache_key} | {current_date}"
        
        # Spin up a completely fresh Google Spreadsheet workbook
        spreadsheet = client.create(sheet_title)
        
        # --- AUTOMATED ACCESS INJECTION ---
        # Crucial fix to bypass file isolation. Grants full editing privileges 
        # to your human Google account instantly upon file creation.
        YOUR_GOOGLE_EMAIL = "your-actual-email@gmail.com"  # <-- CHANGE THIS TO YOUR REAL GOOGLE EMAIL
        spreadsheet.share(YOUR_GOOGLE_EMAIL, perm_type='user', role='writer')
        
        # Define the 5 mandatory tabs for the ledger workbook
        tabs_to_create = [
            "Metrics Data", 
            "Relevant Search Terms", 
            "Irrelevant Search Terms", 
            "Review Queue", 
            "Root Negatives"
        ]
        
        for i, tab_name in enumerate(tabs_to_create):
            # Extract data array from the payload dictionary
            df = pd.DataFrame(data_payload.get(tab_name, []))
            
            # Google Sheets automatically initiates any new workbook with a single tab named 'Sheet1'
            if i == 0:
                worksheet = spreadsheet.get_worksheet(0)
                worksheet.update_title(tab_name)
            else:
                # Add subsequent worksheets cleanly to the workspace
                worksheet = spreadsheet.add_worksheet(title=tab_name, rows="1000", cols="20")
                
            # If data exists for this specific tab, format and dump it to the sheet rows
            if not df.empty:
                # Fill missing or NaN values to prevent API transmission errors
                df = df.fillna("")
                # Convert the dataframe to a list of lists including the headers row
                sheet_data = [df.columns.values.tolist()] + df.values.tolist()
                worksheet.update(sheet_data)
                
        # Return the unique, live browser access URL for the user to open instantly
        return spreadsheet.url
        
    except Exception as e:
        raise RuntimeError(f"Google Drive cloud integration file generation failed: {str(e)}")
