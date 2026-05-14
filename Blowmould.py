import streamlit as st
import pandas as pd
from datetime import datetime
import os
import time
from fpdf import FPDF
import io
import gspread
from google.oauth2.service_account import Credentials

# --- PAGE CONFIGURATION ---
st.set_page_config(layout="wide", page_title="Blowmould Trial Data Entry")

# --- CONFIGURATION ---
MASTER_TRACKER_ID = "1LA9F5mD67vR9yYKqQ39CS-tAZ9QgCgn5KBWaY_RfFKM"
TRIAL_TIMELINE_ID = "1sFfk7Hze5ruQRxgmtHkDnknrfejlqFRX0yKAKkvugd8"

# --- DIRECTORY SETUP ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILENAME_PARQUET = os.path.join(BASE_DIR, "ProjectTracker_Combined.parquet")
SUBMISSIONS_FILE = os.path.join(BASE_DIR, "Trial_Submissions.parquet")

# --- 1. GOOGLE SHEETS AUTH ---
def get_gspread_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        creds_info = st.secrets["connections"]["gsheets"]
    elif "gcp_service_account" in st.secrets:
        creds_info = st.secrets["gcp_service_account"]
    else:
        st.error("Secrets not found! Check your Streamlit Cloud settings.")
        st.stop()

    if isinstance(creds_info, dict) and "private_key" in creds_info:
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
    
    return gspread.authorize(Credentials.from_service_account_info(creds_info, scopes=scope))

# --- 2. DATA HELPERS ---
@st.cache_data
def load_and_clean_parquet():
    if not os.path.exists(FILENAME_PARQUET):
        return None
    try:
        df = pd.read_parquet(FILENAME_PARQUET)
        df['Pre-Prod No.'] = df['Pre-Prod No.'].astype(str).str.split('.').str[0].str.strip()
        return df
    except Exception as e:
        st.error(f"Error reading Parquet: {e}")
        return None

def get_project_data(pre_prod_no):
    df = load_and_clean_parquet()
    if df is None:
        st.warning(f"Database file not found at {FILENAME_PARQUET}.")
        return None
    
    search_id = str(pre_prod_no).strip().split('.')[0]
    result = df[df['Pre-Prod No.'] == search_id]
    
    if not result.empty:
        return result.iloc[0].to_dict()
    else:
        st.warning(f"ID {search_id} not found in the database.")
        return None

def get_next_trial_reference(pre_prod_no):
    if not os.path.exists(SUBMISSIONS_FILE):
        return f"{pre_prod_no}_T1"
    try:
        df = pd.read_parquet(SUBMISSIONS_FILE)
        count = len(df[df['Pre-Prod No.'] == str(pre_prod_no)])
        return f"{pre_prod_no}_T{count + 1}"
    except:
        return f"{pre_prod_no}_T1"

def create_pdf(data):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(190, 10, txt=f"Blowmould Trial Request: {data.get('Trial Reference', 'N/A')}", ln=True, align='C')
    pdf.ln(5)
    
    pdf.set_font("Arial", size=10)
    for key, value in data.items():
        if key != "Observations":
            pdf.set_font("Arial", "B", 10)
            pdf.cell(45, 8, f"{key}:", 0)
            pdf.set_font("Arial", size=10)
            pdf.cell(0, 8, f"{value}", 0, 1)
    
    if data.get("Observations"):
        pdf.ln(5)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 8, "Observations:", 1)
        pdf.set_font("Arial", size=10)
        pdf.multi_cell(0, 8, str(data["Observations"]))

    return pdf.output(dest='S').encode('latin-1', errors='replace')

def update_tracker_status(pre_prod_no, current_trial_ref, manual_date=None):
    try:
        client = get_gspread_client()
        tracker_spreadsheet = client.open_by_key(MASTER_TRACKER_ID)
        tracker_worksheet = tracker_spreadsheet.get_worksheet(0) 
        search_id = str(pre_prod_no).strip().split('.')[0]
        cell = tracker_worksheet.find(search_id, in_column=1)
        
        if not cell: return False, "ID not found"
            
        trial_suffix = current_trial_ref.split('_')[-1]
        date_str = manual_date if manual_date else datetime.now().strftime('%d/%m/%Y')
        combined_value = f"{trial_suffix} - {date_str}"

        headers = [h.strip() for h in tracker_worksheet.row_values(1)]
        if "Blowmould trial requested" in headers:
            col_idx = headers.index("Blowmould trial requested") + 1
            tracker_worksheet.update_cell(cell.row, col_idx, combined_value)
            return True, combined_value
        return False, "Column missing"
    except Exception as e:
        return False, str(e)

# --- SIDEBAR ---
with st.sidebar:
    st.title("Admin")
    if st.button("🔄 Rebuild Local DB"):
        st.cache_data.clear()
        st.success("Cache Cleared")
        st.rerun()

# --- MAIN INTERFACE ---
st.title("Blowmould Trial Data Entry")

# Initialization of session state
if 'submitted' not in st.session_state:
    st.session_state.submitted = False

search_input = st.text_input("Enter Pre-Prod No. (e.g. 11925):")

if search_input:
    ld = get_project_data(search_input)
    
    if ld:
        # 1. SHOW SUCCESS SCREEN IF JUST SUBMITTED
        if st.session_state.submitted:
            st.success("Trial Data successfully recorded!")
            if 'last_submission' in st.session_state:
                pdf_bytes = create_pdf(st.session_state.last_submission)
                st.download_button(
                    label="📥 Download PDF Report",
                    data=pdf_bytes,
                    file_name=f"Trial_{st.session_state.last_submission['Trial Reference']}.pdf",
                    mime="application/pdf"
                )
            
            if st.button("Submit Another Trial"):
                st.session_state.submitted = False
                st.rerun()
        
        # 2. SHOW FORM IF NOT SUBMITTED
        else:
            current_ref = get_next_trial_reference(search_input)
            
            with st.form("trial_form"):
                st.subheader(f"New Trial Entry: {current_ref}")
                
                c1, c2 = st.columns(2)
                client_name = c1.text_input("Client", value=ld.get('Client', ''))
                job_desc = c2.text_input("Description", value=ld.get('Project Description', ''))
                
                c1, c2, c3 = st.columns(3)
                t_date = c1.date_input("Trial Date", datetime.now())
                s_rep = c2.text_input("Sales Rep", value=ld.get('Sales Rep', ''))
                operator = c3.text_input("Operator")
                
                obs = st.text_area("Observations / Notes")
                
                submit_btn = st.form_submit_button("Submit Trial Data")
                
                if submit_btn:
                    # Collect data
                    full_data = {
                        "Trial Reference": current_ref,
                        "Pre-Prod No.": search_input,
                        "Client": client_name,
                        "Description": job_desc,
                        "Date": t_date.strftime("%Y-%m-%d"),
                        "Sales Rep": s_rep,
                        "Operator": operator,
                        "Observations": obs
                    }
                    
                    # Save Locally
                    df_new = pd.DataFrame([full_data])
                    if os.path.exists(SUBMISSIONS_FILE):
                        df_old = pd.read_parquet(SUBMISSIONS_FILE)
                        pd.concat([df_old, df_new], ignore_index=True).to_parquet(SUBMISSIONS_FILE)
                    else:
                        df_new.to_parquet(SUBMISSIONS_FILE)
                    
                    # Save to Cloud
                    try:
                        client_gs = get_gspread_client()
                        update_tracker_status(search_input, current_ref)
                        t_sheet = client_gs.open_by_key(TRIAL_TIMELINE_ID).get_worksheet(0)
                        t_sheet.append_row(list(full_data.values()))
                        
                        # Trigger Success View
                        st.session_state.last_submission = full_data
                        st.session_state.submitted = True
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error during Cloud upload: {e}")