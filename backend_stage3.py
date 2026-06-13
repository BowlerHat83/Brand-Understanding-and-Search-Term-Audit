import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

def push_to_google_sheets(cache_key: str, data_payload: dict) -> str:
    """
    Compiles data frames directly onto distinct spreadsheet tabs via Google Sheets API.
    Returns the live editable workspace direct access URL string.
    """
    # Define API scopes needed
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    try:
        # Load credentials (Streamlit handles secrets injection to files/env variables)
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scopes)
        client = gspread.authorize(creds)
        
        # Format filename convention: Brand Name | Core Offering | YYYY-MM-DD
        current_date = datetime.now().strftime("%Y-%m-%d")
        sheet_title = f"{cache_key} | {current_date}"
        
        # Spin up a completely fresh target worksheet workbook layout container
        spreadsheet = client.create(sheet_title)
        
        # Define target sheets processing list order map
        tabs_to_create = ["Metrics Data", "Relevant Search Terms", "Irrelevant Search Terms", "Review Queue", "Root Negatives"]
        
        for i, tab_name in enumerate(tabs_to_create):
            df = pd.DataFrame(data_payload.get(tab_name, []))
            
            # gspread initiates spreadsheets with one default initial tab called 'Sheet1'
            if i == 0:
                worksheet = spreadsheet.get_worksheet(0)
                worksheet.update_title(tab_name)
            else:
                worksheet = spreadsheet.add_worksheet(title=tab_name, rows="1000", cols="20")
                
            # Direct formatting dump execution onto Google grid pipelines
            if not df.empty:
                worksheet.update([df.columns.values.tolist()] + df.values.tolist())
                
        # Return unique dashboard url identifier key pointer directly back to UI layout
        return spreadsheet.url
        
    except Exception as e:
        raise RuntimeError(f"Google Drive cloud integration file generation failed: {str(e)}")
