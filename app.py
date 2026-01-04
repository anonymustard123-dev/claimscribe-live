import streamlit as st
import google.generativeai as genai
from streamlit_mic_recorder import mic_recorder
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
# 1. SETUP & MODERN STYLING (V7.7 PWA Edition)
# ==========================================
st.set_page_config(page_title="ClaimScribe Pro", page_icon="🛡️", layout="wide")

# 🔑 API KEY (Secure Retrieval)
# This looks for the key in Streamlit's secrets management
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
except FileNotFoundError:
    st.error("⚠️ API Key not found. Please set GOOGLE_API_KEY in your secrets.")
    st.stop()

# --- PWA & STYLING BLOCK ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    .stApp { background-color: #f8fafc; font-family: 'Inter', sans-serif; }
    
    h1, h2, h3 { color: #0f172a; font-weight: 700 !important; letter-spacing: -0.025em; }
    p, div, label, li { color: #334155; font-size: 0.95rem; }

    /* CARD STYLING */
    .input-card { 
        background-color: #ffffff; 
        padding: 2rem; 
        border-radius: 12px; 
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        border: 1px solid #e2e8f0;
        margin-bottom: 20px;
        overflow: visible; 
    }

    /* RECORD BUTTON FIX */
    .stButton button {
        width: 100%;
        border-radius: 8px;
        min-height: 3em; 
    }
    
    div[data-testid="stVerticalBlock"] > div > div[data-testid="stVerticalBlock"] {
        overflow: visible !important;
    }

    /* SIDEBAR & CHAT STYLES */
    section[data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #f1f5f9; }
    .chat-user { background-color: #eff6ff; border: 1px solid #dbeafe; color: #1e3a8a; padding: 12px; border-radius: 12px 12px 0 12px; margin: 8px 0 8px auto; max-width: 85%; }
    .chat-ai { background-color: #ffffff; border: 1px solid #e2e8f0; color: #334155; padding: 12px; border-radius: 12px 12px 12px 0; margin: 8px 0; max-width: 85%; }
    
    /* Code block styling */
    [data-testid="stCodeBlock"] {
        border: 1px solid #cbd5e1;
        border-radius: 8px;
    }
    
    /* Tool Descriptions */
    .tool-desc {
        color: #64748b;
        margin-bottom: 1.5rem;
        font-size: 0.95rem;
    }
</style>

<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
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

# Session State Initialization
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
# 2. SIDEBAR CONFIGURATION
# ==========================================
with st.sidebar:
    st.title("ClaimScribe")
    st.caption("AI Field Assistant v7.7 (PWA)")
    
    st.markdown("---")
    
    st.subheader("1. Client Profile")
    carrier_options = ["State Farm", "Allstate", "Liberty Mutual", "Chubb", "USAA", "Other"]
    selected_carrier = st.selectbox("Select Carrier", carrier_options, label_visibility="collapsed")
    target_carrier = st.text_input("Carrier Name") if selected_carrier == "Other" else selected_carrier

    st.subheader("2. Guidelines")
    with st.expander("📝 Edit Style Rules", expanded=False):
        custom_guidelines = st.text_area("Custom Instructions", height=100, 
            placeholder="e.g. 'Use strict passive voice. Never use the word mold.'")
    
    st.markdown("---")
    
    st.subheader("3. Loss Context")
    loss_type = st.selectbox("Loss Type", ["Water (Pipe Burst)", "Water (Flood)", "Fire/Smoke", "Wind/Hail", "Theft/Vandalism"], label_visibility="collapsed")
    
    if database_loaded:
        st.success("✅ Database Active")
    else:
        st.warning("⚠️ AI Mode (No CSV)")

# ==========================================
# 3. CORE FUNCTIONS
# ==========================================

def analyze_multimodal_batch(audio_list, visual_list):
    genai.configure(api_key=api_key)
    guideline_text = f"STRICTLY FOLLOW: {custom_guidelines}" if custom_guidelines else f"Adopt the standard reporting style of {target_carrier}."
    
    prompt_parts = []
    
    sys_prompt = f"""
    Role: Senior Insurance Adjuster for {target_carrier}.
    Task: Analyze audio/visuals and synthesize a "General Loss Note" (F9) for Xactimate.
    
    CONTEXT: Loss: {loss_type} | {guideline_text}
    
    CRITICAL FORMATTING RULES (Xactimate Compatibility):
    1. NO MARKDOWN. Do not use asterisks (**bold**), underscores, or hash marks (#).
    2. USE UPPERCASE HEADERS. Use all-caps on a new line to denote sections.
    3. PLAIN TEXT ONLY. The output must be ready to paste into a basic text editor.
    4. STYLE: Passive voice, concise, factual.
    
    REQUIRED SECTIONS (Use these exact headers):
    GENERAL OVERVIEW
    ORIGIN AND CAUSE
    RESULTING DAMAGES
    RESTORATION RECOMMENDATIONS
    
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
    (Selector) | (Description) | (Qty)
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

def analyze_statement_batch(audio_list, mime_type="audio/wav"):
    genai.configure(api_key=api_key)
    sys_prompt = f"""
    Role: SIU Expert for {target_carrier}.
    Task: Analyze recorded statements for fraud, timeline inconsistencies, and coverage triggers.
    OUTPUT FORMAT: **Risk Level:** [Low/Med/High] | **🚩 Red Flags:** [List] | **📅 Timeline:** [Reconstruct] | **⚖️ Coverage:** [Suggest exclusions]
    """
    prompt_parts = [sys_prompt]
    for audio_bytes in audio_list:
        prompt_parts.append({"mime_type": mime_type, "data": audio_bytes})
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt_parts)
        return response.text
    except Exception as e:
        st.error(f"Engine Error: {e}")
        return None

def generate_inventory(visual_list):
    genai.configure(api_key=api_key)
    sys_prompt = f"""
    You are a Personal Property Specialist. Review photos of a {loss_type} loss.
    Identify every distinct "Content" item. Ignore building materials.
    OUTPUT FORMAT (Pipe Separated): Item Name | Quantity | Approx Age | Condition | Category
    Do NOT include a header row.
    """
    prompt_parts = [sys_prompt]
    for file_obj in visual_list:
        prompt_parts.append({"mime_type": file_obj.type, "data": file_obj.getvalue()})
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt_parts)
        return response.text
    except Exception as e:
        st.error(f"Engine Error: {e}")
        return None

def audit_scope(current_scope_list):
    scope_str = "\n".join([f"{item['code']} - {item['desc']}" for item in current_scope_list])
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    prompt = f"Scope Auditor. Review this scope: \n{scope_str}\n. Identify MISSING accessory line items for {loss_type}. Return brief bullet points."
    response = model.generate_content(prompt)
    return response.text

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

# ==========================================
# 4. MAIN APP LAYOUT
# ==========================================

st.markdown("### 🛡️ **ClaimScribe**", unsafe_allow_html=True)

tab_scribe, tab_contents, tab_statement, tab_photos, tab_policy, tab_history = st.tabs([
    "🎙️ Field Scribe", "📦 Contents King", "🕵️ Statement Analyzer", "📸 Photos", "🧞 Policy Genie", "📜 History"
])

# --- TAB 1: FIELD SCRIBE ---
with tab_scribe:
    st.markdown('<p class="tool-desc">Create professional Xactimate F9 Notes and preliminary scopes by recording audio and uploading site photos.</p>', unsafe_allow_html=True)
    col1, col2 = st.columns([1, 1], gap="large")
    
    with col1:
        st.markdown('<div class="input-card">', unsafe_allow_html=True)
        st.markdown("#### 1. Capture Field Data")
        
        st.write(" **A. Audio Notes**")
        audio_scribe = mic_recorder(start_prompt="🔴 Record Clip", stop_prompt="⏹️ Stop & Add", key="scribe_rec", use_container_width=True)
        if audio_scribe:
            st.session_state.scribe_audio_buffer.append(audio_scribe['bytes'])
        
        st.write(" **B. Visual Evidence**")
        uploaded_visuals = st.file_uploader("Upload Photos/Videos", type=["jpg", "png", "jpeg", "mp4", "mov"], accept_multiple_files=True, key="scribe_visuals")
        if uploaded_visuals:
            st.session_state.scribe_visual_buffer = uploaded_visuals
        
        aud_count = len(st.session_state.scribe_audio_buffer)
        vis_count = len(st.session_state.scribe_visual_buffer)
        
        if aud_count > 0 or vis_count > 0:
            st.info(f"**Ready:** {aud_count} Audio Clips | {vis_count} Visual Files")
            
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🚀 Generate Report", type="primary"):
                    with st.spinner(f"Synthesizing for Xactimate..."):
                        raw_text = analyze_multimodal_batch(st.session_state.scribe_audio_buffer, st.session_state.scribe_visual_buffer)
                        if raw_text:
                            try:
                                narrative = raw_text.split("---NARRATIVE START---")[1].split("---NARRATIVE END---")[0].strip()
                                scope = raw_text.split("---SCOPE START---")[1].split("---SCOPE END---")[0].strip()
                                
                                scope_items = []
                                for line in scope.split('\n'):
                                    line = line.strip()
                                    if "|" in line:
                                        if "(Selector)" in line and "(Description)" in line:
                                            continue
                                        parts = [p.strip() for p in line.split('|')]
                                        if len(parts) >= 3:
                                            if parts[0] != "(Selector)":
                                                scope_items.append({"code": parts[0], "desc": parts[1], "qty": parts[2]})
                                
                                st.session_state.generated_report = narrative
                                st.session_state.scope_items = scope_items
                                st.session_state.history.append({"time": datetime.datetime.now().strftime("%H:%M"),"carrier": target_carrier,"narrative": narrative})
                                st.session_state.scribe_audio_buffer = []
                                st.session_state.scribe_visual_buffer = []
                                st.rerun()
                            except Exception as e:
                                st.error(f"Parsing Error: {e}")
            with c2:
                if st.button("🗑️ Clear All"):
                    st.session_state.scribe_audio_buffer = []
                    st.session_state.scribe_visual_buffer = []
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    with col2:
        if st.session_state.generated_report:
            st.markdown("#### 2. Xactimate Ready Export")
            
            st.caption("1. Edit the text below if needed.")
            edited_narrative = st.text_area("Edit Narrative", value=st.session_state.generated_report, height=300, label_visibility="collapsed")
            
            st.caption("2. Click the icon in the top-right of the box below to Copy.")
            st.code(edited_narrative, language="text")
            
            st.markdown("---")
            st.markdown("**Preliminary Scope Items**")
            
            df_scope = pd.DataFrame(st.session_state.scope_items) if st.session_state.scope_items else pd.DataFrame(columns=["code", "desc", "qty"])
            edited_df = st.data_editor(df_scope, num_rows="dynamic", use_container_width=True, key="scope_editor", column_config={"code": "Selector", "desc": "Description", "qty": "Qty"})
            final_scope_items = edited_df.to_dict('records')

            col_audit, col_pdf = st.columns(2)
            with col_audit:
                if st.button("🔍 Audit Scope"):
                    with st.spinner("Checking..."):
                        audit_suggestions = audit_scope(final_scope_items)
                        st.info(f"**Findings:**\n\n{audit_suggestions}")
            with col_pdf:
                pdf = generate_pdf(edited_narrative, final_scope_items)
                st.download_button("📄 PDF Report", data=pdf, file_name=f"{target_carrier}_Report.pdf", mime="application/pdf")
        else:
            st.markdown("""<div style="text-align: center; color: #94a3b8; padding: 100px 20px;"><h4>Ready to Scribe</h4><p>Record audio or upload photos.</p></div>""", unsafe_allow_html=True)

# --- TAB 2: CONTENTS KING ---
with tab_contents:
    st.markdown('<p class="tool-desc">Automatically identify, count, and categorize personal property items by uploading room photos.</p>', unsafe_allow_html=True)
    st.markdown('<div class="input-card">', unsafe_allow_html=True)
    col1, col2 = st.columns([1, 1], gap="large")
    with col1:
        st.markdown("#### 1. Upload Room Photos")
        content_photos = st.file_uploader("Room Photos", accept_multiple_files=True, type=['jpg', 'png', 'jpeg'], key="content_upload")
        if content_photos and st.button("📦 Generate Inventory", type="primary"):
            with st.spinner("Scanning items..."):
                raw_csv = generate_inventory(content_photos)
                if raw_csv:
                    parsed_items = []
                    for line in raw_csv.split('\n'):
                        if "|" in line:
                            parts = [p.strip() for p in line.split('|')]
                            if len(parts) >= 4:
                                parsed_items.append({"Item": parts[0], "Qty": parts[1], "Age": parts[2], "Condition": parts[3], "Category": parts[4] if len(parts) > 4 else "General"})
                    st.session_state.contents_data = parsed_items
    with col2:
        if st.session_state.contents_data:
            st.markdown("#### 2. Inventory List")
            df_contents = pd.DataFrame(st.session_state.contents_data)
            edited_contents = st.data_editor(df_contents, num_rows="dynamic", use_container_width=True, key="contents_editor")
            csv = edited_contents.to_csv(index=False).encode('utf-8')
            st.download_button("⬇️ Download CSV", csv, "Contents_Inventory.csv", "text/csv")
    st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 3: STATEMENT ANALYZER ---
with tab_statement:
    st.markdown('<p class="tool-desc">Analyze recorded interviews for timeline inconsistencies, coverage triggers, and potential fraud indicators.</p>', unsafe_allow_html=True)
    st.markdown('<div class="input-card">', unsafe_allow_html=True)
    col1, col2 = st.columns([1, 1], gap="large")
    with col1:
        st.markdown("#### 1. Interview Recording")
        audio_statement = mic_recorder(start_prompt="🔴 Record Interview", stop_prompt="⏹️ Stop & Add", key="stmt_rec", use_container_width=True)
        if audio_statement: st.session_state.statement_audio_buffer.append(audio_statement['bytes'])
        if len(st.session_state.statement_audio_buffer) > 0:
            if st.button("🕵️ Analyze Statement", type="primary"):
                with st.spinner("Analyzing..."):
                    st.session_state.statement_analysis = analyze_statement_batch(st.session_state.statement_audio_buffer)
                    st.session_state.statement_audio_buffer = [] 
                    st.rerun()
            if st.button("🗑️ Reset", key="reset_stmt"):
                st.session_state.statement_audio_buffer = []
                st.rerun()
    with col2:
        if st.session_state.statement_analysis:
            st.markdown("#### 2. Analysis")
            st.markdown(st.session_state.statement_analysis)
    st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 4: PHOTO ENGINE ---
with tab_photos:
    st.markdown('<p class="tool-desc">Batch rename hundreds of site photos automatically using AI (e.g., "Kitchen_Overview_Damaged.jpg").</p>', unsafe_allow_html=True)
    st.markdown('<div class="input-card">', unsafe_allow_html=True)
    st.markdown("#### 📸 Batch Photo Renamer")
    photos = st.file_uploader("Select Photos", accept_multiple_files=True, type=['jpg', 'png', 'jpeg'], label_visibility="collapsed")
    if photos and st.button("⚡ Process Batch", type="primary"):
        zip_data = process_photos(photos)
        st.session_state.renamed_zip = zip_data
        st.success("Processing Complete!")
    if st.session_state.renamed_zip:
        st.download_button(label="⬇️ Download ZIP", data=st.session_state.renamed_zip, file_name=f"{target_carrier}_Photos.zip", mime="application/zip", type="primary")
    st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 5: POLICY GENIE ---
with tab_policy:
    st.markdown('<p class="tool-desc">Upload a PDF policy and ask complex coverage questions to get instant, cited answers.</p>', unsafe_allow_html=True)
    st.markdown('<div class="input-card">', unsafe_allow_html=True)
    st.markdown("#### 🧞 Policy Genie")
    policy_pdf = st.file_uploader("Upload PDF", type="pdf", label_visibility="collapsed")
    if policy_pdf:
        if not st.session_state.policy_text:
            with st.spinner("Reading Policy..."):
                reader = PdfReader(policy_pdf)
                text = ""
                for page in reader.pages: text += page.extract_text() + "\n"
                st.session_state.policy_text = text
                st.success("Policy Loaded!")
    if st.session_state.policy_text:
        user_q = st.text_input("Ask a question:", placeholder="e.g. Is mold covered?")
        if user_q:
            with st.spinner("Analyzing..."):
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel("gemini-2.5-flash")
                prompt = f"""Expert Coverage Counsel. Answer based on POLICY TEXT. Cite sections. USER QUESTION: {user_q} POLICY TEXT: {st.session_state.policy_text}"""
                response = model.generate_content(prompt)
                st.session_state.chat_history.append(("user", user_q))
                st.session_state.chat_history.append(("ai", response.text))
        for role, msg in st.session_state.chat_history:
            st.markdown(f'<div class="chat-{role}">{msg}</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 6: HISTORY ---
with tab_history:
    st.markdown('<p class="tool-desc">View and retrieve reports generated in previous sessions.</p>', unsafe_allow_html=True)
    st.markdown("#### 📜 Session History")
    if st.session_state.history:
        for item in reversed(st.session_state.history):
            with st.expander(f"{item['time']} - {item['carrier']}"):
                st.code(item['narrative'], language="text")
    else:
        st.info("No reports generated yet.")
