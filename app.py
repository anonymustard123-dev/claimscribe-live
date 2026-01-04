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

# 🔑 API KEY (Secure Retrieval)
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
except FileNotFoundError:
    st.error("⚠️ API Key not found. Please set GOOGLE_API_KEY in your secrets.")
    st.stop()

# ==========================================
# 2. PWA & "NUCLEAR" STYLING
# ==========================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* --- FORCE CLEAN LOOK --- */
    .stApp { 
        font-family: 'Inter', sans-serif;
    }
    
    /* --- HIDE ALL STREAMLIT BRANDING (The "Pet Project" Remover) --- */
    
    /* 1. Hide the top colored decoration bar */
    header[data-testid="stHeader"] {
        display: none !important;
    }
    
    /* 2. Hide the "Hosted with Streamlit" Footer */
    footer {
        display: none !important;
        visibility: hidden !important;
        height: 0px !important;
    }
    
    /* 3. Hide the Hamburger Menu & Github Icon */
    #MainMenu {
        display: none !important;
        visibility: hidden !important;
    }
    .stDeployButton {
        display: none !important;
    }
    
    /* 4. Hide the "Stop Recording" container border to make it look native */
    [data-testid="stAudioInput"] {
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 10px;
        background: white;
    }

    /* --- CARD STYLING --- */
    .input-card { 
        background-color: #ffffff; 
        padding: 1.5rem; 
        border-radius: 12px; 
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        border: 1px solid #e2e8f0;
        margin-bottom: 20px;
    }

    /* --- BUTTON STYLING --- */
    .stButton button {
        background-color: #2563eb !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2) !important;
    }

    /* --- MOBILE PADDING --- */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 3rem !important;
    }
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
if "statement_audio_buffer" not in st.session_state: st.session_state.statement_audio_buffer = []
if "statement_analysis" not in st.session_state: st.session_state.statement_analysis = None
if "scribe_visual_buffer" not in st.session_state: st.session_state.scribe_visual_buffer = []
if "contents_data" not in st.session_state: st.session_state.contents_data = []

# ==========================================
# 3. LOGIC FUNCTIONS
# ==========================================

def analyze_multimodal_batch(audio_list, visual_list):
    genai.configure(api_key=api_key)
    guideline_text = f"STRICTLY FOLLOW: {custom_guidelines}" if custom_guidelines else f"Adopt the standard reporting style of {target_carrier}."
    
    prompt_parts = []
    
    sys_prompt = f"""
    Role: Senior Insurance Adjuster for {target_carrier}.
    Task: Analyze audio/visuals and synthesize a "General Loss Note" (F9) for Xactimate.
    
    CONTEXT: Loss: {loss_type} | {guideline_text}
    
    CRITICAL FORMATTING RULES:
    1. NO MARKDOWN. No bold (**), no italics, no hash marks (#).
    2. USE UPPERCASE HEADERS on their own lines.
    3. PLAIN TEXT ONLY.
    
    OUTPUT STRUCTURE:
    ---NARRATIVE START---
    GENERAL OVERVIEW
    [Date of loss, time, and facts of loss]

    ORIGIN AND CAUSE
    [Specific mechanism of injury]

    RESULTING DAMAGES
    [Room by room breakdown based on visual evidence]

    RESTORATION RECOMMENDATIONS
    [Mitigation and repair steps]
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
        st.error(f"Engine Error: {e}")
        return None

def extract_scope_items(raw_text):
    items = []
    try:
        if "---SCOPE START---" not in raw_text:
            return []
        scope_block = raw_text.split("---SCOPE START---")[1].split("---SCOPE END---")[0]
        for line in scope_block.split('\n'):
            line = line.strip()
            if line.startswith('|'): line = line[1:]
            if line.endswith('|'): line = line[:-1]
            if "|" in line:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 3:
                    if "---" in parts[0] or "Selector" in parts[0]: continue
                    items.append({"code": parts[0], "desc": parts[1], "qty": parts[2]})
    except Exception as e:
        print(f"Scope Parse Error: {e}")
    return items

def audit_scope(current_scope_list):
    scope_str = "\n".join([f"{item['code']} - {item['desc']}" for item in current_scope_list])
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    prompt = f"Scope Auditor. Review this scope: \n{scope_str}\n. Identify MISSING accessory line items for {loss_type}. Return brief bullet points."
    response = model.generate_content(prompt)
    return response.text

def generate_pdf(narrative, scope_data):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    story = []
    styles = getSampleStyleSheet()
    story.append(Paragraph(f"{target_carrier} Field Report", styles['Title']))
    story.append(Paragraph(f"Loss: {loss_type} | Date: {datetime.datetime.now().strftime('%Y-%m-%d')}", styles['Normal']))
    story.append(Spacer(1, 24))
    formatted_narrative = narrative.replace("\n", "<br/>")
    story.append(Paragraph("<b>Risk Narrative</b>", styles['Heading2']))
    story.append(Paragraph(formatted_narrative, styles['Normal']))
    story.append(Spacer(1, 24))
    if scope_data:
        story.append(Paragraph("<b>Preliminary Scope</b>", styles['Heading2']))
        table_data = [["Selector", "Description", "Qty"]] 
        for item in scope_data:
            table_data.append([item['code'], item['desc'], item['qty']])
        t = Table(table_data, colWidths=[80, 300, 50])
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),('GRID', (0, 0), (-1, -1), 1, colors.black),('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),]))
        story.append(t)
    doc.build(story)
    buffer.seek(0)
    return buffer

def analyze_statement_batch(audio_list, mime_type="audio/wav"):
    genai.configure(api_key=api_key)
    prompt = f"Role: SIU Expert. Analyze audio for fraud/coverage issues. Output: Risk Level, Red Flags, Timeline."
    prompt_parts = [prompt]
    for audio_bytes in audio_list:
        prompt_parts.append({"mime_type": mime_type, "data": audio_bytes})
    model = genai.GenerativeModel("gemini-2.5-flash")
    return model.generate_content(prompt_parts).text

def generate_inventory(visual_list):
    genai.configure(api_key=api_key)
    prompt = f"Personal Property Specialist. Identify items in photos. Output CSV format: Item|Qty|Age|Condition|Category. No headers."
    prompt_parts = [prompt]
    for file_obj in visual_list:
        prompt_parts.append({"mime_type": file_obj.type, "data": file_obj.getvalue()})
    model = genai.GenerativeModel("gemini-2.5-flash")
    return model.generate_content(prompt_parts).text

def process_photos(uploaded_files):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    renamed_images = []
    progress_bar = st.progress(0)
    for i, file in enumerate(uploaded_files):
        try:
            image_data = Image.open(file)
            prompt = f"Rename photo for {target_carrier} claim. Format: Room_Label_Condition.jpg. Return ONLY filename."
            response = model.generate_content([prompt, image_data])
            new_name = response.text.strip().replace(" ", "_").replace(".jpg", "") + ".jpg"
            renamed_images.append((new_name, file))
        except:
            renamed_images.append((f"Image_{i}.jpg", file))
        progress_bar.progress((i + 1) / len(uploaded_files))
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for name, original_file in renamed_images:
            original_file.seek(0)
            zip_file.writestr(name, original_file.read())
    return zip_buffer.getvalue()

# ==========================================
# 4. MAIN LAYOUT
# ==========================================

with st.sidebar:
    st.title("ClaimScribe")
    st.caption("AI Field Assistant v7.9")
    
    st.subheader("1. Client Profile")
    carrier_options = ["State Farm", "Allstate", "Liberty Mutual", "Chubb", "USAA", "Other"]
    selected_carrier = st.selectbox("Select Carrier", carrier_options, label_visibility="collapsed")
    target_carrier = st.text_input("Carrier Name") if selected_carrier == "Other" else selected_carrier

    st.subheader("2. Guidelines")
    with st.expander("📝 Edit Style Rules"):
        custom_guidelines = st.text_area("Instructions", height=80, placeholder="e.g. Strict passive voice.")
    
    st.subheader("3. Loss Context")
    loss_type = st.selectbox("Loss Type", ["Water (Pipe Burst)", "Water (Flood)", "Fire/Smoke", "Wind/Hail", "Theft/Vandalism"], label_visibility="collapsed")
    
    if database_loaded:
        st.success("✅ Database Active")
    else:
        st.warning("⚠️ AI Mode (No CSV)")

# --- MAIN TABS ---
tab_scribe, tab_contents, tab_statement, tab_photos, tab_policy, tab_history = st.tabs([
    "🎙️ Scribe", "📦 Contents", "🕵️ Statement", "📸 Photos", "🧞 Policy", "📜 History"
])

with tab_scribe:
    col1, col2 = st.columns([1, 1], gap="large")
    
    with col1:
        st.markdown('<div class="input-card">', unsafe_allow_html=True)
        st.markdown("#### 1. Capture Field Data")
        
        st.write(" **A. Audio Notes**")
        # NATIVE AUDIO INPUT (Clean Look)
        audio_scribe = st.audio_input("Record Note", label_visibility="collapsed")
        
        st.write(" **B. Visual Evidence**")
        uploaded_visuals = st.file_uploader("Upload Photos/Videos", type=["jpg", "png", "jpeg", "mp4", "mov"], accept_multiple_files=True, key="scribe_visuals")
        if uploaded_visuals:
            st.session_state.scribe_visual_buffer = uploaded_visuals
        
        # Audio handling for native input
        has_audio = audio_scribe is not None
        vis_count = len(st.session_state.scribe_visual_buffer)
        
        if has_audio or vis_count > 0:
            st.info(f"**Ready:** {'Audio Set' if has_audio else 'No Audio'} | {vis_count} Visual Files")
            
            if st.button("🚀 Generate Report", type="primary"):
                with st.spinner("Synthesizing..."):
                    # Wrap audio in list for processing
                    audio_list = [audio_scribe.getvalue()] if audio_scribe else []
                    
                    raw_text = analyze_multimodal_batch(audio_list, st.session_state.scribe_visual_buffer)
                    if raw_text:
                        try:
                            if "---NARRATIVE START---" in raw_text:
                                narrative = raw_text.split("---NARRATIVE START---")[1].split("---NARRATIVE END---")[0].strip()
                            else:
                                narrative = raw_text 
                            
                            scope_items = extract_scope_items(raw_text)
                            
                            st.session_state.generated_report = narrative
                            st.session_state.scope_items = scope_items
                            st.session_state.history.append({"time": datetime.datetime.now().strftime("%H:%M"),"carrier": target_carrier,"narrative": narrative})
                            st.rerun()
                        except Exception as e:
                            st.error(f"Parsing Error: {e}")
            
            if st.button("🗑️ Clear All", type="secondary"):
                st.session_state.scribe_visual_buffer = []
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    with col2:
        if st.session_state.generated_report:
            st.markdown("#### 2. Xactimate Export")
            
            edited_narrative = st.text_area("Edit Narrative", value=st.session_state.generated_report, height=300, label_visibility="collapsed")
            st.caption("Tap icon to copy:")
            st.code(edited_narrative, language="text")
            
            st.markdown("---")
            st.markdown("**Preliminary Scope**")
            
            df_scope = pd.DataFrame(st.session_state.scope_items) if st.session_state.scope_items else pd.DataFrame(columns=["code", "desc", "qty"])
            edited_df = st.data_editor(df_scope, num_rows="dynamic", use_container_width=True, key="scope_editor", column_config={"code": "Selector", "desc": "Description", "qty": "Qty"})
            final_scope_items = edited_df.to_dict('records')

            c_audit, c_pdf = st.columns(2)
            with c_audit:
                if st.button("🔍 Audit"):
                    with st.spinner("Checking..."):
                        audit_suggestions = audit_scope(final_scope_items)
                        st.info(f"{audit_suggestions}")
            with c_pdf:
                pdf = generate_pdf(edited_narrative, final_scope_items)
                st.download_button("📄 PDF", data=pdf, file_name="Report.pdf", mime="application/pdf")

# (Other tabs are standard)
with tab_contents:
    col1, col2 = st.columns(2)
    with col1:
        img = st.file_uploader("Photos", accept_multiple_files=True, key="content_up")
        if img and st.button("Generate Inv"):
            res = generate_inventory(img)
            st.session_state.contents_data = [{"Item": l.split('|')[0], "Qty": l.split('|')[1]} for l in res.split('\n') if '|' in l]
    with col2:
        if st.session_state.contents_data:
            st.data_editor(st.session_state.contents_data)

with tab_photos:
    p = st.file_uploader("Photos", accept_multiple_files=True, key="photo_up")
    if p and st.button("Process"):
        st.session_state.renamed_zip = process_photos(p)
        st.success("Done")
    if st.session_state.renamed_zip:
        st.download_button("Download ZIP", st.session_state.renamed_zip, "photos.zip")

with tab_statement:
    # UPDATED TO NATIVE AUDIO INPUT
    audio = st.audio_input("Record Statement", key="stmt")
    if audio and st.button("Analyze"):
        st.write(analyze_statement_batch([audio.getvalue()]))
