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
    """Loads the main database and cleans the Pre-Prod No. column."""
    if not os.path.exists(FILENAME_PARQUET):
        return None
    try:
        df = pd.read_parquet(FILENAME_PARQUET)
        # Standardize ID column: string, no decimals, no whitespace
        df['Pre-Prod No.'] = df['Pre-Prod No.'].astype(str).str.split('.').str[0].str.strip()
        return df
    except Exception as e:
        st.error(f"Error reading Parquet: {e}")
        return None

def get_project_data(pre_prod_no):
    df = load_and_clean_parquet()
    if df is None:
        # If Rebuild deleted the file, this warning triggers correctly
        st.warning(f"Database file not found at {FILENAME_PARQUET}. Please ensure it is present in your repository.")
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
    df = pd.read_parquet(SUBMISSIONS_FILE)
    count = len(df[df['Pre-Prod No.'] == str(pre_prod_no)])
    return f"{pre_prod_no}_T{count + 1}"

def create_pdf(data):
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Arial", "B", 14)
    pdf.cell(190, 10, txt=f"Blowmould Trial Request: {data.get('Trial Reference', 'N/A')}", ln=True, align='C')
    pdf.ln(2)

    pdf.set_font("Arial", "B", 10)
    pdf.cell(30, 8, "Client:", border=0)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 8, txt=str(data.get("Client", "N/A")), ln=True)

    pdf.set_font("Arial", "B", 10)
    pdf.cell(30, 8, "Description:", border=0)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 8, txt=str(data.get("Description", "N/A")), ln=True)
    
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
    pdf.ln(5)

    to_exclude = ["Trial Reference", "Client", "Description", "Observations"]
    grid_data = {k: v for k, v in data.items() if k not in to_exclude}
    
    line_height = 5.5
    pdf.set_font("Arial", size=8)
    items = list(grid_data.items())
    midpoint = (len(items) + 1) // 2
    
    start_y = pdf.get_y()
    for key, value in items[:midpoint]:
        pdf.set_font("Arial", "B", 8)
        pdf.cell(35, line_height, txt=f"{key}:", border=0)
        pdf.set_font("Arial", size=8)
        pdf.cell(55, line_height, txt=str(value)[:40], border=0, ln=True)
        
    end_y_left = pdf.get_y()
    pdf.set_y(start_y)
    for key, value in items[midpoint:]:
        pdf.set_x(105)
        pdf.set_font("Arial", "B", 8)
        pdf.cell(35, line_height, txt=f"{key}:", border=0)
        pdf.set_font("Arial", size=8)
        pdf.cell(55, line_height, txt=str(value)[:40], border=0, ln=True)

    pdf.set_y(max(end_y_left, pdf.get_y()) + 5)
    obs_text = data.get("Observations", "")
    if obs_text:
        pdf.set_font("Arial", "B", 9)
        pdf.cell(0, 7, "Observations:", ln=True)
        pdf.set_font("Arial", size=8)
        pdf.multi_cell(190, 5, txt=str(obs_text))

    return pdf.output(dest='S').encode('latin-1', errors='replace')

def update_tracker_status(pre_prod_no, current_trial_ref, manual_date=None):
    try:
        client = get_gspread_client()
        tracker_spreadsheet = client.open_by_key(MASTER_TRACKER_ID)
        tracker_worksheet = tracker_spreadsheet.get_worksheet(0) 

        search_id = str(pre_prod_no).strip().split('.')[0]
        cell = tracker_worksheet.find(search_id, in_column=1)
        
        if not cell:
            return False, f"ID {search_id} not found."
            
        trial_suffix = current_trial_ref.split('_')[-1] if '_' in current_trial_ref else current_trial_ref
        date_str = manual_date if manual_date else datetime.now().strftime('%d/%m/%Y')
        combined_value = f"{trial_suffix} - {date_str}"

        headers = [h.strip() for h in tracker_worksheet.row_values(1)]
        col_name = "Blowmould trial requested"
        
        if col_name in headers:
            col_idx = headers.index(col_name) + 1
            tracker_worksheet.update_cell(cell.row, col_idx, combined_value)
            return True, combined_value
        return False, "Column not found."
    except Exception as e:
        return False, str(e)

def sync_last_trial_to_cloud(pre_prod_no):
    if not os.path.exists(SUBMISSIONS_FILE):
        return False, "No history file found."
    try:
        df_history = pd.read_parquet(SUBMISSIONS_FILE)
        df_history['Pre-Prod No.'] = df_history['Pre-Prod No.'].astype(str)
        project_history = df_history[df_history['Pre-Prod No.'] == str(pre_prod_no)].copy()
        
        if project_history.empty:
            return update_tracker_status(pre_prod_no, "None", manual_date=" ") 

        project_history['Trial_Num'] = project_history['Trial Reference'].str.extract(r'(\d+)$').astype(int)
        latest_trial = project_history.sort_values(by=['Trial_Num'], ascending=False).iloc[0]
        
        return update_tracker_status(
            pre_prod_no, 
            latest_trial['Trial Reference'], 
            manual_date=datetime.strptime(latest_trial['Date'], '%Y-%m-%d').strftime('%d/%m/%Y')
        )
    except Exception as e:
        return False, f"Sync Error: {str(e)}"

# --- SIDEBAR ---
with st.sidebar:
    st.title("Quick Links")
    st.page_link("https://projecttracker-kc2ksaezfqxarnv96ugzdk.streamlit.app/", label="📋 Go to Project Tracker", icon="🚀")
    st.page_link("https://injectiontrial-996rcfrtn9rkgafzsejzrn.streamlit.app/", label="Injection Trial App", icon="🧪")
    st.divider()

    # REBUILD LOGIC: Clears cache so load_and_clean_parquet runs fresh
    if st.button("🔄 Rebuild Local DB", use_container_width=True):
        st.cache_data.clear()
        # Note: If the file is tracked by Git, os.remove might not be necessary 
        # unless you are generating the file dynamically. 
        # For a GitHub-hosted file, st.cache_data.clear() is usually enough.
        st.success("Cache Rebuilt!")
        time.sleep(1)
        st.rerun()
    
    st.header("Admin Controls")
    if st.button("♻️ Refresh Cache"):
        st.cache_data.clear()
        st.success("Cache Cleared")
    
    st.subheader("Manage Trials")
    if os.path.exists(SUBMISSIONS_FILE):
        hist_df = pd.read_parquet(SUBMISSIONS_FILE)
        if not hist_df.empty:
            trial_labels = hist_df.apply(lambda x: f"{x['Trial Reference']} ({x['Date']})", axis=1).tolist()
            selected_label = st.selectbox("Select Trial to Remove", options=trial_labels)
            selected_ref = str(selected_label).split(" (")[0]
            
            if st.button("🗑️ Delete from Local & Cloud", type="primary"):
                try:
                    client_gs = get_gspread_client()
                    t_sheet = client_gs.open_by_key(TRIAL_TIMELINE_ID).get_worksheet(0)
                    cell = t_sheet.find(selected_ref)
                    if cell:
                        t_sheet.delete_rows(cell.row)
                    
                    updated_df = hist_df[hist_df['Trial Reference'] != selected_ref]
                    updated_df.to_parquet(SUBMISSIONS_FILE, index=False)
                    
                    pre_id = selected_ref.split('_')[0]
                    sync_last_trial_to_cloud(pre_id)
                    st.success(f"Deleted {selected_ref}")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Deletion failed: {e}")
        else:
            st.info("No submissions found.")

# --- 4. MAIN INTERFACE ---
st.title("Blowmould Trial Data Entry")
search_input = st.text_input("Enter Pre-Prod No. (e.g. 11925):")

if search_input:
    ld = get_project_data(search_input)
    if ld:
        current_trial_ref = get_next_trial_reference(search_input)

        if st.session_state.get('submitted', False):
            st.success(f"Success! {current_trial_ref} recorded.")
            if 'last_submission' in st.session_state:
                pdf_bytes = create_pdf(st.session_state.last_submission)
                st.download_button("📥 Download PDF", pdf_bytes, f"Report_{current_trial_ref}.pdf")
            if st.button("Start Next Entry"):
                st.session_state.submitted = False
                st.rerun()

        with st.form("trial_entry_form", clear_on_submit=True):
            st.subheader(f"Trial Reference: {current_trial_ref}")
            top_c1, top_c2 = st.columns([1, 2])
            client = top_c1.text_input("Client", value=ld.get('Client', ''))
            desc = top_c2.text_input("Job Description", value=ld.get('Project Description', ''))
            
            st.divider() 
            c1, c2, c3 = st.columns(3)
            t_date = c1.date_input("Trial Date", datetime.now())
            s_rep = c2.text_input("Sales Rep", value=ld.get('Sales Rep', ''))
            operator = c3.text_input("Operator Name")

            c1, c2, c3, c4 = st.columns(4)
            target = c1.text_input("Target To", value=ld.get('Target to', ''))
            qty = c2.number_input("Trial Qty", step=1)
            m_prod = c3.text_input("Prod Machine", value=ld.get('Machine', ''))
            m_trial = c4.text_input("Trial Machine")

            st.markdown("### Product Specifications")
            c1, c2, c3 = st.columns(3)
            p_code = c1.text_input("Product Code", value=ld.get('Product Code', ''))
            mat = c2.text_input("Material", value=ld.get('Material', ''))
            supp = c3.text_input("Supplier", value=ld.get('Supplier', ''))

            c1, c2, c3, c4 = st.columns(4)
            product_height = c1.text_input("Height", value=str(ld.get('Height', '')))
            grade_of_material = c2.text_input("Grade of Material", value=str(ld.get('Grade of Material', '')))
            product_diam = c3.text_input("Diameter", value=str(ld.get('Diameter', '')))
            mix = c4.text_input("Mix %", value=str(ld.get('Mix_%', '')))

            c1, c2, c3, c4 = st.columns(4)
            lid_info = c1.text_input("Lid", value=ld.get('Lid', '')) 
            item_colour = c2.text_input("Item Colour", value=ld.get('Item Colour', ''))
            pigment_grade = c3.text_input("Pigment_MB Grade", value=ld.get('Pigment_MB Grade', ''))
            tinuvin = c4.radio("Tinuvin?", ["Yes", "No"], horizontal=True)

            c1, c2, c3, c4, c5 = st.columns(5)
            drawing_number = c1.text_input("Drawing No.", value=str(ld.get('Drawing No', '')))
            m_no = c2.text_input("Mould No.", value=str(ld.get('Mould No.', '')))
            machine_no = c3.text_input("Machine No.", value=str(ld.get('Machine No.', '')))
            cavs = c4.text_input("Cavities", value=str(ld.get('Cavities', '')))
            screw_diam = c5.text_input("Screw Diameter (IML only)", value=str(ld.get('Screw Diameter(IML only)', '')))

            st.markdown("### Dosing & Machine Settings")
            c1, c2, c3, c4, c5 = st.columns(5)
            c_set = c1.text_input("Colour Set")
            c_act = c2.text_input("Colour Act")
            c_per = c3.text_input("Colour %")
            s_weight = c4.text_input("Shot Weight")
            d_time = c5.text_input("Dosing Time")

            c1, c2 = st.columns(2)
            cycle = c1.text_input("Cycle", value=str(ld.get('Cycle', '')))
            mass = c2.text_input("Mass", value=str(ld.get('Mass', '')))
            obs = st.text_area("Observations")

if st.form_submit_button("Submit Trial Data"):
                # 1. Prepare data (ensure all values are converted to string for Google Sheets)
                full_row = {
                    "Trial Reference": str(current_trial_ref),
                    "Pre-Prod No.": str(search_input),
                    "Client": str(client), 
                    "Description": str(desc),
                    "Date": t_date.strftime("%Y-%m-%d"),
                    "Sales Rep": str(s_rep), 
                    "Operator": str(operator),
                    "Target": str(target), 
                    "Qty": str(qty),
                    "Prod Machine": str(m_prod), 
                    "Trial Machine": str(m_trial),
                    "Product Code": str(p_code), 
                    "Material": str(mat), 
                    "Supplier": str(supp),
                    "Height": str(product_height), 
                    "Grade": str(grade_of_material),
                    "Diameter": str(product_diam), 
                    "Mix %": str(mix),
                    "Lid": str(lid_info), 
                    "Colour": str(item_colour), 
                    "Pigment": str(pigment_grade),
                    "Tinuvin": str(tinuvin), 
                    "Drawing": str(drawing_number), 
                    "Mould No": str(m_no),
                    "Machine No": str(machine_no), 
                    "Cavities": str(cavs), 
                    "Screw Diam": str(screw_diam),
                    "Colour Set": str(c_set), 
                    "Colour Act": str(c_act), 
                    "Colour %": str(c_per),
                    "Shot Weight": str(s_weight), 
                    "Dosing Time": str(d_time), 
                    "Cycle": str(cycle), 
                    "Mass": str(mass),
                    "Observations": str(obs)
                }

                # 2. Save Locally First (Parquet)
                df_new = pd.DataFrame([full_row])
                if os.path.exists(SUBMISSIONS_FILE):
                    df_hist = pd.read_parquet(SUBMISSIONS_FILE)
                    pd.concat([df_hist, df_new], ignore_index=True).to_parquet(SUBMISSIONS_FILE, index=False)
                else:
                    df_new.to_parquet(SUBMISSIONS_FILE, index=False)

                # 3. Save to Cloud
                try:
                    with st.spinner("Uploading to Google Sheets..."):
                        client_gs = get_gspread_client()
                        
                        # Update Task 1: Master Project Tracker (Success/Date)
                        update_tracker_status(search_input, current_trial_ref)
                        
                        # Update Task 2: Blowmould Timeline Spreadsheet
                        # We verify the sheet exists before appending
                        ts_spreadsheet = client_gs.open_by_key(TRIAL_TIMELINE_ID)
                        t_sheet = ts_spreadsheet.get_worksheet(0) # Grabs the first tab
                        
                        # Convert dict values to a flat list for append_row
                        row_to_append = list(full_row.values())
                        t_sheet.append_row(row_to_append)
                    
                    # 4. Success State & Rerun
                    st.session_state.last_submission = full_row
                    st.session_state.submitted = True
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Cloud Sync failed: {str(e)}")
                    # We don't rerun here so the user can see the error