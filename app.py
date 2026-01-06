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
import os

# ==========================================
# 1. SETUP & CONFIG
# ==========================================
st.set_page_config(
    page_title="ClaimScribe", 
    page_icon="🛡️", 
    layout="wide",
    initial_sidebar_state="collapsed" # Starts closed to keep it clean
)

# 🔑 API KEY
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
    except (FileNotFoundError, KeyError):
        st.error("⚠️ API Key not found. Please set GOOGLE_API_KEY.")
        st.stop()

# ==========================================
# 2. MODERN UI & CSS (V7.18 - "SAAS LOOK")
# ==========================================
st.markdown("""
<style>
    /* --- FONTS --- */
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

    /* --- ROOT VARIABLES --- */
    :root {
        --primary: #2563eb; /* Stronger Blue */
        --bg-color: #f8fafc; /* Very light cool grey */
        --card-bg: #ffffff;
        --text-dark: #0f172a;
        --text-grey: #64748b;
        --input-bg: #f1f5f9; /* "Filled" input style */
    }

    .stApp {
        background-color: var(--bg-color) !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
    }

    /* --- CLEAN HEADER --- */
    .stApp > header { display: none !important; }
    
    .custom-header {
        text-align: center;
        padding: 2rem 1rem 1rem 1rem;
        margin-bottom: 1rem;
    }
    .custom-header h1 {
        color: var(--text-dark) !important;
        margin: 0;
        font-size: 1.8rem;
        font-weight: 800; /* Extra Bold */
        letter-spacing: -0.03em;
    }
    .custom-header p {
        color: var(--text-grey) !important;
        font-weight: 500;
        font-size: 0.9rem;
        margin-top: 0.2rem;
    }

    /* --- CARDS (Softer & Cleaner) --- */
    .input-card { 
        background-color: var(--card-bg);
        padding: 1.5rem; 
        border-radius: 20px; /* More rounded */
        box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.05); /* Soft, spread out shadow */
        border: 1px solid rgba(255,255,255,0.5);
        margin-bottom: 24px;
    }

    /* --- MODERN INPUTS ("Filled" Style) --- */
    /* Removes borders, adds light grey background */
    div[data-baseweb="select"] > div, 
    input[type="text"], 
    textarea {
        background-color: var(--input-bg) !important;
        border: 1px solid transparent !important;
        color: var(--text-dark) !important;
        border-radius: 12px !important;
        padding: 10px 12px !important;
        transition: all 0.2s ease;
    }
    /* Focus: White bg + Blue Border + Shadow */
    div[data-baseweb="select"] > div:focus-within,
    input:focus, textarea:focus {
        background-color: #ffffff !important;
        border: 1px solid var(--primary) !important;
        box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.1) !important;
    }

    /* --- BUTTONS (Flat & Punchy) --- */
    div.stButton > button {
        background-color: var(--primary) !important;
        color: white !important;
        border: none !important;
        border-radius: 12px !important;
        font-weight: 600 !important;
        height: 3.5rem !important;
        transition: all 0.2s;
        box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.3); /* Blue shadow */
    }
    div.stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(37, 99, 235, 0.4);
    }
    div.stButton > button:active {
        transform: scale(0.97);
    }
    
    /* Secondary Button (Clear All) */
    div.stButton > button[kind="secondary"] {
        background-color: white !important;
        color: var(--text-grey) !important;
        border: 2px solid #e2e8f0 !important;
        box-shadow: none !important;
    }

    /* --- AUDIO RECORDER (Sleek) --- */
    [data-testid="stAudioInput"] {
        background-color: var(--input-bg) !important;
        border: none !important;
        padding: 16px;
        border-radius: 16px;
    }

    /* --- HIDE JANK --- */
    header { visibility: hidden !important; }
    footer { display: none !important; }
    #MainMenu { display: none !important; }
    .stDeployButton { display: none !important; }

    /* --- CUSTOM LOADER --- */
    .loader-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 2rem;
        color: var(--primary);
    }
    .pulse-ring {
        display: inline-block;
        width: 50px;
        height: 50px;
        border-radius: 50%;
        background: var(--primary);
        animation: pulse-ring 1.5s cubic-bezier(0.215, 0.61, 0.355, 1) infinite;
    }
    .loader-text {
        margin-top: 1rem;
        font-weight: 600;
        font-size: 0.85rem;
        color: var(--text-grey) !important;
        letter-spacing: 0.05em;
    }
    @keyframes pulse-ring {
        0% { transform: scale(0.8); opacity: 0.8; }
        100% { transform: scale(2); opacity: 0; }
    }
</style>

<meta name="apple-mobile-web-app-title" content="ClaimScribe">
<link rel="apple-touch-icon" href="https://em-content.zobj.net/source/apple/354/shield_1f6e1-fe0f.png">
<link rel="shortcut icon" href="https://em-content.zobj.net/source/apple/354/shield_1f6e1-fe0f.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#f8fafc"> 
""", unsafe_allow_html=True)

# Session State
if "generated_report" not in st.session_state: st.session_state.generated_report = None
if "scope_items" not in st.session_state: st.session_state.scope_items = []
if "renamed_zip" not in st.session_state: st.session_state.renamed_zip = None
if "scribe_visual_buffer" not in st.session_state: st.session_state.scribe_visual_buffer = []
if "contents_data" not in st.session_state: st.session_state.contents_data = []

# ==========================================
# 3. LOGIC (FUNCTIONS)
# ==========================================

def get_custom_loader(text="Processing..."):
    return f"""
    <div class="loader-container">
        <div class="pulse-ring"></div>
        <div class="loader-text">{text.upper()}</div>
    </div>
    """

def analyze_multimodal_batch(audio_list, visual_list, carrier, loss_type, guidelines):
    genai.configure(api_key=api_key)
    guide_text = f"STRICTLY FOLLOW: {guidelines}" if guidelines else f"Adopt the standard reporting style of {carrier}."
    
    prompt_parts = []
    sys_prompt = f"""
    Role: Senior Adjuster for {carrier}.
    Task: Write Xactimate F9 Note.
    CONTEXT: Loss: {loss_type} | {guide_text}
    RULES: 1. NO MARKDOWN. 2. UPPERCASE HEADERS. 3. PLAIN TEXT.
    
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

# --- SIDEBAR (Settings Moved Here) ---
with st.sidebar:
    st.header("⚙️ Job Settings")
    carrier_options = ["State Farm", "Allstate", "Liberty Mutual", "Chubb", "USAA", "Other"]
    selected_carrier = st.selectbox("Carrier", carrier_options)
    target_carrier = st.text_input("Name") if selected_carrier == "Other" else selected_carrier
    loss_type = st.selectbox("Loss Type", ["Water (Pipe Burst)", "Water (Flood)", "Fire/Smoke", "Wind/Hail", "Theft/Vandalism"])
    custom_guidelines = st.text_area("Guideline Overrides", placeholder="e.g. Strict passive voice...", height=100)
    st.markdown("---")
    st.caption(f"App v7.18 | {target_carrier}")

# --- MAIN CONTENT ---
st.markdown("""
    <div class="custom-header">
        <h1>🛡️ ClaimScribe</h1>
        <p>AI Field Assistant</p>
    </div>
""", unsafe_allow_html=True)

# --- TABS ---
tab_scribe, tab_contents, tab_statement, tab_photos, tab_policy = st.tabs([
    "🎙️ Scribe", "📦 Contents", "🕵️ Statement", "📸 Photos", "🧞 Policy"
])

# --- TAB 1: SCRIBE ---
with tab_scribe:
    st.markdown('<div class="input-card">', unsafe_allow_html=True)
    st.markdown("##### 1. Capture Field Data")
    audio_scribe = st.audio_input("Record Field Note", label_visibility="collapsed")
    uploaded_visuals = st.file_uploader("Upload Photos/Videos", type=["jpg", "png", "jpeg", "mp4", "mov"], accept_multiple_files=True, key="scribe_visuals")
    if uploaded_visuals: st.session_state.scribe_visual_buffer = uploaded_visuals
    
    # Action Buttons
    has_audio = audio_scribe is not None
    vis_count = len(st.session_state.scribe_visual_buffer)
    
    if has_audio or vis_count > 0:
        st.info(f"**Ready:** {'Audio Set' if has_audio else 'No Audio'} | {vis_count} Files")
        
        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            if st.button("🚀 Generate Report", type="primary", use_container_width=True):
                loader_placeholder = st.empty()
                loader_placeholder.markdown(get_custom_loader("Synthesizing Report..."), unsafe_allow_html=True)
                
                audio_list = [audio_scribe.getvalue()] if audio_scribe else []
                raw = analyze_multimodal_batch(audio_list, st.session_state.scribe_visual_buffer, target_carrier, loss_type, custom_guidelines)
                
                loader_placeholder.empty()
                if raw:
                    narrative = raw.split("---NARRATIVE START---")[1].split("---NARRATIVE END---")[0].strip() if "---NARRATIVE START---" in raw else raw
                    scope = extract_scope_items(raw)
                    st.session_state.generated_report = narrative
                    st.session_state.scope_items = scope
                    st.rerun()
        
        with col_btn2:
             if st.button("🗑️ Clear", type="secondary", use_container_width=True):
                st.session_state.scribe_visual_buffer = []
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # Results
    if st.session_state.generated_report:
        st.markdown('<div class="input-card">', unsafe_allow_html=True)
        st.markdown("##### 2. Export")
        edited_narrative = st.text_area("Narrative", value=st.session_state.generated_report, height=300)
        st.markdown("**Scope Items**")
        df_scope = pd.DataFrame(st.session_state.scope_items) if st.session_state.scope_items else pd.DataFrame(columns=["code", "desc", "qty"])
        final_scope = st.data_editor(df_scope, use_container_width=True, num_rows="dynamic").to_dict('records')
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔍 Audit Scope", use_container_width=True):
                with st.spinner("Auditing..."):
                    res = audit_scope(final_scope, loss_type)
                st.info(res)
        with c2:
            pdf = generate_pdf(edited_narrative, final_scope, target_carrier, datetime.datetime.now().strftime('%Y-%m-%d'))
            st.download_button("📄 PDF Export", data=pdf, file_name="Report.pdf", mime="application/pdf", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 2: CONTENTS ---
with tab_contents:
    st.markdown('<div class="input-card">', unsafe_allow_html=True)
    st.markdown("##### Room Inventory")
    img = st.file_uploader("Upload Room Photos", accept_multiple_files=True, key="content_up")
    
    contents_loader_placeholder = st.empty()

    if img and st.button("Analyze Items", use_container_width=True, type="primary"):
        contents_loader_placeholder.markdown(get_custom_loader("Scanning Items..."), unsafe_allow_html=True)
        res = generate_inventory(img)
        st.session_state.contents_data = [{"Item": l.split('|')[0], "Qty": l.split('|')[1]} for l in res.split('\n') if '|' in l]
        contents_loader_placeholder.empty()

    if st.session_state.contents_data:
        st.data_editor(st.session_state.contents_data, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 3: STATEMENT ---
with tab_statement:
    st.markdown('<div class="input-card">', unsafe_allow_html=True)
    st.markdown("##### Fraud Analysis")
    stmt_audio = st.audio_input("Record Interview", key="stmt_rec")
    if stmt_audio and st.button("Analyze Risks", type="primary", use_container_width=True):
        with st.spinner("Analyzing voice patterns..."):
            st.write(analyze_statement_batch([stmt_audio.getvalue()]))
    st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 4: PHOTOS ---
with tab_photos:
    st.markdown('<div class="input-card">', unsafe_allow_html=True)
    st.markdown("##### Batch Rename")
    p = st.file_uploader("Select Photos", accept_multiple_files=True, key="photo_up")
    if p and st.button("Rename All", type="primary", use_container_width=True):
        with st.spinner("Processing metadata..."):
            st.session_state.renamed_zip = process_photos(p, target_carrier)
        st.success("Complete!")
    if st.session_state.renamed_zip:
        st.download_button("Download ZIP", st.session_state.renamed_zip, "photos.zip", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 5: POLICY ---
with tab_policy:
    st.markdown('<div class="input-card">', unsafe_allow_html=True)
    st.info("Upload policy PDF (Feature simplified for PWA)")
    st.markdown('</div>', unsafe_allow_html=True)
