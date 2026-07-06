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


def update_brand_profile_cache(cache_key: str, new_relevant_terms: list, new_irrelevant_terms: list):
    """
    Appends new human-classified items directly back into the core Stage 1
    Brand Profile spreadsheet cache row to intelligently expand long-term knowledge.
    """
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    gc = gspread.authorize(creds)
    
    # Open your master central configuration tracking sheet
    sheet = gc.open_by_key(st.secrets["CACHE_SPREADSHEET_ID"]).sheet1
    records = sheet.get_all_records()
    
    row_index = None
    target_row_data = {}
    
    # Locate the active campaign profile row matching this exact workspace cache key
    for idx, row in enumerate(records, start=2):
        if str(row.get("Profile Name", "")).strip() == str(cache_key).strip():
            row_index = idx
            target_row_data = row
            break
            
    if not row_index:
        # If the row doesn't match or exist in cache records yet, abort write safely
        return False

    # --- PROCESS AND CONSOLIDATE TARGET RELEVANT / PROTECTED TERMS ---
    existing_protected_raw = str(target_row_data.get("Protected Terms", "")).strip()
    existing_protected_list = [item.strip() for item in existing_protected_raw.split(",") if item.strip()] if existing_protected_raw else []
    
    # Append fresh additions, filtering out case-insensitive duplicates
    for term in new_relevant_terms:
        clean_term = str(term).strip()
        if clean_term.lower() not in [x.lower() for x in existing_protected_list]:
            existing_protected_list.append(clean_term)


def update_brand_profile_cache(cache_key, new_relevant_terms=None, new_irrelevant_terms=None):
    """
    Appends freshly triaged human feedback terms back into the Stage 1 Google Sheet 
    cache layer to permanently train the brand profile.
    """
    try:
        import streamlit as st
        import gspread
        from google.oauth2.service_account import Credentials

        # 1. Authenticate with Google Sheets using existing credentials
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        gc = gspread.authorize(creds)
        
        # 2. Open the cache sheet
        sheet = gc.open_by_key(st.secrets["CACHE_SPREADSHEET_ID"]).sheet1
        records = sheet.get_all_records()
        
        # Helper function to parse existing cell strings back into clean sets
        def parse_cell_to_set(val):
            if not val:
                return set()
            return {item.strip() for item in str(val).split(",") if item.strip()}

        # 3. Search for the row matching the brand signature
        row_index = None
        target_row = None
        for idx, row in enumerate(records, start=2):
            # Match against the base profile name (e.g., "Brand Name")
            if str(row.get("Profile Name", "")).split(" | ")[0].strip() == str(cache_key).split(" | ")[0].strip():
                row_index = idx
                target_row = row
                break
                
        if not row_index:
            # Fallback: if no exact profile row is found, we cannot patch it safely
            return False

        # 4. Pull existing arrays from sheet row
        current_variants = parse_cell_to_set(target_row.get("Brand Variants", ""))
        current_protected = parse_cell_to_set(target_row.get("Protected Terms", ""))
        current_competitors = parse_cell_to_set(target_row.get("Competitors", ""))
        current_irrelevant = parse_cell_to_set(target_row.get("Irrelevant Terms", ""))
        current_languages = target_row.get("Allowed Languages", "English")

        # 5. Inject the new human-approved items into the right buckets
        if new_relevant_terms:
            for term in new_relevant_terms:
                # Relevant user selections are highly likely to be core protected offering descriptors
                current_protected.add(term.strip())
                
        if new_irrelevant_terms:
            for term in new_irrelevant_terms:
                # Irrelevant user selections expand your negative target definitions
                current_irrelevant.add(term.strip())

        # 6. Re-compile lists back into comma-separated text strings
        row_payload = [
            target_row.get("Profile Name"),
            ", ".join(sorted(list(current_variants))),
            ", ".join(sorted(list(current_protected))),
            ", ".join(sorted(list(current_competitors))),
            ", ".join(sorted(list(current_irrelevant))),
            current_languages
        ]
        
        # 7. Commit changes back to Google Sheets row range
        sheet.update(range_name=f"A{row_index}:F{row_index}", values=[row_payload])
        return True

    except Exception as e:
        # Prevent breaking the application state flow if Google API drops
        print(f"Error logging triage feedback to sheet: {str(e)}")
        return False
            
    updated_protected_cell_string = ", ".join(existing_protected_list)

    # --- PROCESS AND CONSOLIDATE TARGET IRRELEVANT / EXCLUSION TERMS ---
    existing_irrelevant_raw = str(target_row_data.get("Irrelevant Terms", "")).strip()
    existing_irrelevant_list = [item.strip() for item in existing_irrelevant_raw.split(",") if item.strip()] if existing_irrelevant_raw else []
    
    # Append fresh additions, filtering out case-insensitive duplicates
    for term in new_irrelevant_terms:
        clean_term = str(term).strip()
        if clean_term.lower() not in [x.lower() for x in existing_irrelevant_list]:
            existing_irrelevant_list.append(clean_term)
            
    updated_irrelevant_cell_string = ", ".join(existing_irrelevant_list)

    # --- SUBMIT MODIFIED PAYLOAD TO EXCEL CELLS (COLUMNS C AND E) ---
    # Column C = Protected Terms, Column E = Irrelevant Terms
    sheet.update(range_name=f"C{row_index}", values=[[updated_protected_cell_string]])
    sheet.update(range_name=f"E{row_index}", values=[[updated_irrelevant_cell_string]])
    
    return True
