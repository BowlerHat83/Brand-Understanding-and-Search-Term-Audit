import pandas as pd
import io
import streamlit as st
from datetime import datetime, timezone

def push_to_google_sheets(cache_key: str, payload: dict):
    """
    Bypasses Google APIs completely to eliminate 403 Quota errors.
    Flattens the multi-tab dictionary payload into a single, unified 
    CSV byte stream for a reliable browser download.
    """
    try:
        all_data_frames = []
        
        # Loop through each tab's rows in the payload
        for tab_name, rows in payload.items():
            if not rows:
                continue
                
            # Convert list of dicts to a DataFrame if data exists
            if isinstance(rows, list) and len(rows) > 0 and isinstance(rows[0], dict):
                df = pd.DataFrame(rows)
                
                # Insert a clear tag column at the front so you can filter by tab in Google Sheets
                df.insert(0, 'Source_Tab', tab_name)
                all_data_frames.append(df)
        
        if not all_data_frames:
            st.error("No valid data found to compile into a CSV ledger.")
            return None
            
        # Combine all sections into one clean, continuous master data table
        master_df = pd.concat(all_data_frames, ignore_index=True)
        
        # Write to a string buffer using standard CSV configuration
        csv_buffer = io.StringIO()
        master_df.to_csv(csv_buffer, index=False, encoding='utf-8')
        
        # Convert string to bytes stream for Streamlit download handling
        bytes_data = csv_buffer.getvalue().encode('utf-8')
        return bytes_data
        
    except Exception as e:
        st.error(f"Local CSV compilation failed: {str(e)}")
        return None

def update_brand_profile_cache(cache_key: str, profile_data: dict) -> bool:
    """
    Keeps the backend cache helper available so app.py imports do not break.
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
