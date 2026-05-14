import streamlit as st
import pandas as pd
from datetime import datetime
import os
from fpdf import FPDF
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
    
    # Prioritize 'gsheets' secret structure
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        creds_info = st.secrets["connections"]["gsheets"]
    elif "gcp_service_account" in st.secrets:
        creds_info = st.secrets["gcp_service_account"]
    else:
        st.error("Secrets not found! Please check your Streamlit Cloud 'Secrets' settings.")
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
        # Ensure ID is a clean string
        df['Pre-Prod No.'] = df['Pre-Prod No.'].astype(str).str.split('.').str[0].str.strip()
        return df
    except Exception as e:
        st.error(f"Error reading local database: {e}")
        return None

def get_project_data(pre_prod_no):
    df = load_and_clean_parquet()
    if df is None:
        return None
    
    search_id = str(pre_prod_no).strip().split('.')[0]
    result = df[df['Pre-Prod No.'] == search_id]
    
    return result.iloc[0].to_dict() if not result.empty else None

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
    pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 10, txt="Blowmould Trial Report", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", size=11)
    for key, value in data.items():
        if key != "Observations":
            pdf.set_font("Arial", "B", 11)
            pdf.cell(50, 8, f"{key}:", 0)
            pdf.set_font("Arial", size=11)
            pdf.cell(0, 8, f"{value}", 0, 1)
    
    if data.get("Observations"):
        pdf.ln(5)
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 10, "Observations:", "B", 1)
        pdf.set_font("Arial", size=11)
        pdf.multi_cell(0, 8, str(data["Observations"]))

    return pdf.output(dest='S').encode('latin-1', errors='replace')

# --- SIDEBAR ---
with st.sidebar:
    st.title("Settings")
    if st.button("🔄 Clear App Cache"):
        st.cache_data.clear()
        st.success("Cache Cleared!")

# --- MAIN INTERFACE ---
st.title("Blowmould Trial Data Entry")

# Use session state to handle the workflow
if 'submitted' not in st.session_state:
    st.session_state.submitted = False

# Reset submission state if search input changes
search_input = st.text_input("Enter Pre-Prod No. (e.g. 11925):", key="search_bar")

if search_input:
    project_info = get_project_data(search_input)
    
    if project_info:
        # FLOW A: SUCCESS SCREEN
        if st.session_state.submitted:
            st.balloons()
            st.success(f"✅ Trial data for {search_input} successfully uploaded!")
            
            if 'last_submission' in st.session_state:
                pdf_bytes = create_pdf(st.session_state.last_submission)
                st.download_button(
                    label="📥 Download Trial PDF",
                    data=pdf_bytes,
                    file_name=f"Trial_Report_{st.session_state.last_submission['Trial Reference']}.pdf",
                    mime="application/pdf"
                )
            
            if st.button("Start New Entry"):
                st.session_state.submitted = False
                st.rerun()

        # FLOW B: DATA ENTRY FORM
        else:
            current_ref = get_next_trial_reference(search_input)
            
            with st.form("trial_form", clear_on_submit=False):
                st.subheader(f"New Trial Reference: {current_ref}")
                
                col1, col2 = st.columns(2)
                client = col1.text_input("Client", value=project_info.get('Client', ''))
                desc = col2.text_input("Description", value=project_info.get('Project Description', ''))
                
                col3, col4, col5 = st.columns(3)
                trial_date = col3.date_input("Trial Date", datetime.now())
                sales_rep = col4.text_input("Sales Rep", value=project_info.get('Sales Rep', ''))
                operator = col5.text_input("Operator")
                
                observations = st.text_area("Observations / Results")
                
                submit_clicked = st.form_submit_button("Submit to Tracker")
                
                if submit_clicked:
                    submission_data = {
                        "Trial Reference": current_ref,
                        "Pre-Prod No.": search_input,
                        "Client": client,
                        "Description": desc,
                        "Date": trial_date.strftime("%Y-%m-%d"),
                        "Sales Rep": sales_rep,
                        "Operator": operator,
                        "Observations": observations
                    }
                    
                    # 1. Save Locally
                    df_new = pd.DataFrame([submission_data])
                    if os.path.exists(SUBMISSIONS_FILE):
                        df_old = pd.read_parquet(SUBMISSIONS_FILE)
                        pd.concat([df_old, df_new], ignore_index=True).to_parquet(SUBMISSIONS_FILE)
                    else:
                        df_new.to_parquet(SUBMISSIONS_FILE)
                    
                    # 2. Save to Google Sheets
                    try:
                        client_gs = get_gspread_client()
                        # Update the Timeline Sheet
                        t_sheet = client_gs.open_by_key(TRIAL_TIMELINE_ID).get_worksheet(0)
                        t_sheet.append_row(list(submission_data.values()))
                        
                        # Set session state and rerun to show success screen
                        st.session_state.last_submission = submission_data
                        st.session_state.submitted = True
                        st.rerun()
                    except Exception as e:
                        st.error(f"Cloud Save Failed: {e}")
    else:
        st.error(f"Could not find project details for ID: {search_input}")