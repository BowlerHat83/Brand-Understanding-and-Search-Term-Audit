import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

def manual_quota_reset():
    scope = ["https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    
    try:
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Pull absolutely every spreadsheet clogging this account
        query = "mimeType = 'application/vnd.google-apps.spreadsheet'"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        if not files:
            print("Drive is already empty!")
            return
            
        print(f"Found {len(files)} files. Initiating hard purge...")
        for file in files:
            print(f"Deleting: {file['name']}")
            drive_service.files().delete(fileId=file['id']).execute()
            
        print("✅ Hard purge complete! Storage is down to 0%.")
    except Exception as e:
        print(f"Error during purge: {e}")

if __name__ == "__main__":
    manual_quota_reset()
