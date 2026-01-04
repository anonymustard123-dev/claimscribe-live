import streamlit as st
import google.generativeai as genai
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
import io
import datetime
import pandas as pd
import zipfile
import re
from PIL import Image
from pypdf import PdfReader

# ==========================================
# 1. SETUP & CONFIG
# ==========================================
st.set_page_config(
    page_title="ClaimScribe", 
    page_icon="🛡️", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 🔑 API KEY
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
except FileNotFoundError:
    st.error("⚠️ API Key not found.")
    st.stop()

# ==========================================
# 2. PWA & HIGH-CONTRAST STYLING
# ==========================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* --- ROOT VARIABLES (Force Light Mode) --- */
    :root {
        --primary-color: #2563eb;
        --background-color: #ffffff;
        --secondary-background-color: #f8fafc;
        --text-color: #0f172a;
        --font: 'Inter', sans-serif;
    }
    
    /* --- GLOBAL RESET --- */
    .stApp {
        background-color: #ffffff !important;
        font-family: 'Inter', sans-serif;
    }
    
    /* --- TEXT VISIBILITY FIX (The "Weird Color" Fix) --- */
    /* Forces high-contrast dark text everywhere */
    h1, h2, h3, h4, h5, h6, p, li, div, label, span {
        color: #0f172a !important;
    }
    /* Muted text for descriptions */
    .tool-desc {
        color: #475569 !important;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
        line-height: 1.5;
    }

    /* --- TAB TEXT --- */
    button[data-baseweb="tab"] div p {
        color: #0f172a !important; 
        font-weight: 600;
    }
    /* Active tab highlight */
    button[data-baseweb="tab"][aria-selected="true"] div p {
        color: #2563eb !important;
    }

    /* --- EXPANDER (JOB SETUP) --- */
    .streamlit-expanderHeader {
        background-color: #f1f5f9 !important;
        color: #0f172a !important;
        border-radius: 8px;
    }
    .streamlit-expanderContent {
        background-color: #ffffff !important;
        color: #0f172a !important;
        border: 1px solid #e2e8f0;
        border-top: none;
    }

    /* --- INPUTS & RECORDER --- */
    [data-testid="stAudioInput"] {
        background-color: #f8fafc !important;
        border: 1px solid #cbd5e1 !important;
        padding: 10px;
        border-radius: 12px;
    }
    /* Input fields background */
    input, textarea, .stSelectbox > div > div {
        background-color: #ffffff !important;
        color: #0f172a !important;
        border-color: #cbd5e1 !important;
    }

    /* --- BUTTONS --- */
    div.stButton > button {
        background-color: #2563eb !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        height: 3rem !important;
        box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2);
    }

    /* --- HIDE STREAMLIT CHROME --- */
    header { visibility: hidden !important; }
    footer { display: none !important; }
    #MainMenu { display: none !important; }
    .stDeployButton { display: none !important; }
    
</style>

<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="theme-color" content="#ffffff">
""", unsafe_allow_html=True)

# Load Truth Data
@st.cache_data
def load_truth_data():
    try:
        df = pd.read_csv("codes.csv")
        return df.to_string(index=False), True
    except FileNotFoundError:
        return "", False

xactimate_database, database_loaded = load_truth_data()

# Session State
if "history" not in st.session_state: st.session_state.history = []
if "generated_report" not in st.session_state: st.session_state.generated_report = None
if "scope_items" not in st.session_state: st.session_state.scope_items = []
if "renamed_zip" not in st.session_state: st.session_state.renamed_zip = None
if "policy_text" not in st.session_state: st.session_state.policy_text = ""
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "scribe_audio_buffer" not in st.session_state: st.session_state.scribe_audio_buffer = []
if "scribe_visual_buffer" not in st.session_state: st.session_state.scribe_visual_buffer = []
if "contents_data" not in st.session_state: st.session_state.contents_data = []

# ==========================================
# 3. LOGIC (FUNCTIONS)
# ==========================================

def analyze_multimodal_batch(audio_list, visual_list, carrier, loss_type, guidelines):
    genai.configure(api_key=api_key)
    guide_text = f"STRICTLY FOLLOW: {guidelines}" if guidelines else f"Adopt the standard reporting style of {carrier}."
    
    prompt_parts = []
    sys_prompt = f"""
    Role: Senior Adjuster for {carrier}.
    Task: Write Xactimate F9 Note.
    CONTEXT: Loss: {loss_type} | {guide_text}
    
    RULES:
    1. NO MARKDOWN (No bold, italics).
    2. UPPERCASE HEADERS.
    3. PLAIN TEXT.
    
    SECTIONS:
    GENERAL OVERVIEW
    ORIGIN AND CAUSE
    RESULTING DAMAGES
    RESTORATION RECOMMENDATIONS
    
    OUTPUT STRUCTURE:
    ---NARRATIVE START---
    GENERAL OVERVIEW
    [Details]

    ORIGIN AND CAUSE
    [Details]

    RESULTING DAMAGES
    [Details]

    RESTORATION RECOMMENDATIONS
    [Details]
    ---NARRATIVE END---
    
    ---SCOPE START---
    Selector | Description | Qty
    ---SCOPE END---
    """
    prompt_parts.append(sys_prompt)
    for audio_bytes in audio_list:
        prompt_parts.append({"mime_type": "audio/wav", "data": audio_bytes})
    for file_obj in visual_list:
        prompt_parts.append({"mime_type": file_obj.type, "data": file_obj.getvalue()})

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt_parts)
        return response.text
    except Exception as e:
        return None

def extract_scope_items(raw_text):
    items = []
    try:
        if "---SCOPE START---" not in raw_text: return []
        scope_block = raw_text.split("---SCOPE START---")[1].split("---SCOPE END---")[0]
        for line in scope_block.split('\n'):
            line = line.strip()
            if line.startswith('|'): line = line[1:]
            if line.endswith('|'): line = line[:-1]
            if "|" in line:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 3 and "Selector" not in parts[0] and "---" not in parts[0]:
                    items.append({"code": parts[0], "desc": parts[1], "qty": parts[2]})
    except: pass
    return items

def audit_scope(current_scope_list, loss_type):
    scope_str = "\n".join([f"{item['code']} - {item['desc']}" for item in current_scope_list])
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(f"Audit this scope for missing {loss_type} items: \n{scope_str}")
    return response.text

def generate_pdf(narrative, scope_data, carrier, date):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    story = []
    styles = getSampleStyleSheet()
    story.append(Paragraph(f"{carrier} Field Report", styles['Title']))
    story.append(Paragraph(f"Date: {date}", styles['Normal']))
    story.append(Spacer(1, 24))
    story.append(Paragraph("<b>Risk Narrative</b>", styles['Heading2']))
    story.append(Paragraph(narrative.replace("\n", "<br/>"), styles['Normal']))
    story.append(Spacer(1, 24))
    if scope_data:
        story.append(Paragraph("<b>Preliminary Scope</b>", styles['Heading2']))
        table_data = [["Selector", "Description", "Qty"]] 
        for item in scope_data:
            table_data.append([item['code'], item['desc'], item['qty']])
        t = Table(table_data, colWidths=[80, 300, 50])
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),('GRID', (0, 0), (-1, -1), 1, colors.black)]))
        story.append(t)
    doc.build(story)
    buffer.seek(0)
    return buffer

def analyze_statement_batch(audio_list):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    prompt_parts = ["Analyze statement for fraud/coverage.", {"mime_type": "audio/wav", "data": audio_list[0]}]
    return model.generate_content(prompt_parts).text

def generate_inventory(visual_list):
    genai.configure(api_key=api_key)
    prompt_parts = ["Identify items. CSV format: Item|Qty. No header."]
    for f in visual_list: prompt_parts.append({"mime_type": f.type, "data": f.getvalue()})
    model = genai.GenerativeModel("gemini-2.5-flash")
    return model.generate_content(prompt_parts).text

def process_photos(uploaded_files, carrier):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    renamed_images = []
    for file in uploaded_files:
        try:
            image_data = Image.open(file)
            res = model.generate_content([f"Rename for {carrier} claim. Format: Room_Label.jpg", image_data])
            renamed_images.append((res.text.strip(), file))
        except: pass
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for name, original_file in renamed_images:
            original_file.seek(0)
            zip_file.writestr(name, original_file.read())
    return zip_buffer.getvalue()

# ==========================================
# 4. MAIN LAYOUT
# ==========================================

# --- HEADER ---
st.title("ClaimScribe")
st.caption("AI Field Assistant v7.12")

# --- JOB SETUP (Main Page) ---
with st.expander("📋 **Job Setup & Carrier**", expanded=True):
    col_a, col_b = st.columns(2)
    with col_a:
        carrier_options = ["State Farm", "Allstate", "Liberty Mutual", "Chubb", "USAA", "Other"]
        selected_carrier = st.selectbox("Carrier", carrier_options)
        target_carrier = st.text_input("Name") if selected_carrier == "Other" else selected_carrier
    with col_b:
        loss_type = st.selectbox("Loss Type", ["Water (Pipe Burst)", "Water (Flood)", "Fire/Smoke", "Wind/Hail", "Theft/Vandalism"])
    
    custom_guidelines = st.text_area("Custom Guidelines (Optional)", placeholder="e.g. Strict passive voice...", height=68)

st.markdown("---")

# --- TABS ---
tab_scribe, tab_contents, tab_statement, tab_photos, tab_policy = st.tabs([
    "🎙️ Scribe", "📦 Contents", "🕵️ Statement", "📸 Photos", "🧞 Policy"
])

# --- TAB 1: SCRIBE ---
with tab_scribe:
    st.markdown('<p class="tool-desc">Record audio notes and upload photos to generate professional Xactimate F9 Notes and preliminary scopes.</p>', unsafe_allow_html=True)
    
    # 1. Capture
    st.markdown("##### 1. Capture Field Data")
    audio_scribe = st.audio_input("Record Field Note", label_visibility="collapsed")
    uploaded_visuals = st.file_uploader("Upload Photos/Videos", type=["jpg", "png", "jpeg", "mp4", "mov"], accept_multiple_files=True, key="scribe_visuals")
    if uploaded_visuals: st.session_state.scribe_visual_buffer = uploaded_visuals
    
    # Logic
    has_audio = audio_scribe is not None
    vis_count = len(st.session_state.scribe_visual_buffer)
    
    if has_audio or vis_count > 0:
        st.info(f"**Ready:** {'Audio Set' if has_audio else 'No Audio'} | {vis_count} Files")
        
        if st.button("🚀 Generate Report", type="primary"):
            with st.spinner("Synthesizing..."):
                audio_list = [audio_scribe.getvalue()] if audio_scribe else []
                raw = analyze_multimodal_batch(audio_list, st.session_state.scribe_visual_buffer, target_carrier, loss_type, custom_guidelines)
                
                if raw:
                    narrative = raw.split("---NARRATIVE START---")[1].split("---NARRATIVE END---")[0].strip() if "---NARRATIVE START---" in raw else raw
                    scope = extract_scope_items(raw)
                    st.session_state.generated_report = narrative
                    st.session_state.scope_items = scope
                    st.rerun()
        
        if st.button("🗑️ Clear All", type="secondary"):
            st.session_state.scribe_visual_buffer = []
            st.rerun()

    # Results
    if st.session_state.generated_report:
        st.markdown("---")
        st.markdown("##### 2. Export")
        edited_narrative = st.text_area("Narrative", value=st.session_state.generated_report, height=300)
        st.caption("Tap to copy:")
        st.code(edited_narrative, language="text")
        
        st.markdown("**Scope Items**")
        df_scope = pd.DataFrame(st.session_state.scope_items) if st.session_state.scope_items else pd.DataFrame(columns=["code", "desc", "qty"])
        final_scope = st.data_editor(df_scope, use_container_width=True, num_rows="dynamic").to_dict('records')
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔍 Audit"):
                res = audit_scope(final_scope, loss_type)
                st.info(res)
        with c2:
            pdf = generate_pdf(edited_narrative, final_scope, target_carrier, datetime.datetime.now().strftime('%Y-%m-%d'))
            st.download_button("📄 PDF", data=pdf, file_name="Report.pdf", mime="application/pdf")

# --- TAB 2: CONTENTS ---
with tab_contents:
    st.markdown('<p class="tool-desc">Upload room photos to automatically identify, count, and categorize personal property items.</p>', unsafe_allow_html=True)
    img = st.file_uploader("Room Photos", accept_multiple_files=True, key="content_up")
    if img and st.button("List Items"):
        res = generate_inventory(img)
        st.session_state.contents_data = [{"Item": l.split('|')[0], "Qty": l.split('|')[1]} for l in res.split('\n') if '|' in l]
    if st.session_state.contents_data:
        st.data_editor(st.session_state.contents_data)

# --- TAB 3: STATEMENT ---
with tab_statement:
    st.markdown('<p class="tool-desc">Analyze recorded interviews for timeline inconsistencies, coverage triggers, and fraud indicators.</p>', unsafe_allow_html=True)
    stmt_audio = st.audio_input("Record Interview", key="stmt_rec")
    if stmt_audio and st.button("Analyze Statement"):
        st.write(analyze_statement_batch([stmt_audio.getvalue()]))

# --- TAB 4: PHOTOS ---
with tab_photos:
    st.markdown('<p class="tool-desc">Batch rename hundreds of site photos automatically using AI (e.g., "Kitchen_Overview_Damaged.jpg").</p>', unsafe_allow_html=True)
    p = st.file_uploader("Photos to Rename", accept_multiple_files=True, key="photo_up")
    if p and st.button("Rename Batch"):
        st.session_state.renamed_zip = process_photos(p, target_carrier)
        st.success("Done!")
    if st.session_state.renamed_zip:
        st.download_button("Download ZIP", st.session_state.renamed_zip, "photos.zip")

# --- TAB 5: POLICY ---
with tab_policy:
    st.markdown('<p class="tool-desc">Upload a PDF policy to ask complex coverage questions and get instant, cited answers.</p>', unsafe_allow_html=True)
    st.info("Upload policy PDF (Feature simplified for PWA)")
