import streamlit as st
from lecture_processor import process_input, process_pdf
from auth import show_auth_page, is_authenticated, get_current_user, logout
import os
import time
from datetime import datetime
import json
import base64


def load_enhanced_css():
    with open("style.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

st.set_page_config(
    page_title="📚 Exam Study Notes Generator",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)


load_enhanced_css()

logo_path = "silvy_logo.png"
if os.path.exists(logo_path):
    with open(logo_path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode()
        st.markdown(f"""
        <div style='text-align: center; margin-top: -2rem; margin-bottom: 1rem;'>
            <img src="data:image/png;base64,{encoded}" style='height: 80px;' />
        </div>
        """, unsafe_allow_html=True)


# =============================================
# Authentication Gate
# =============================================
if not is_authenticated():
    show_auth_page()
    st.stop()

# =============================================
# Main App (only shown when logged in)
# =============================================
user = get_current_user()

if 'processing' not in st.session_state:
    st.session_state.processing = False
if 'history' not in st.session_state:
    st.session_state.history = []
if 'current_result' not in st.session_state:
    st.session_state.current_result = None

st.markdown("""
<div class="main-header fade-in">
    <div class="main-title">📚 Exam Study Notes Generator</div>
    <div class="subtitle">Transform lectures & PDFs into comprehensive study materials for exam success</div>
    <div style="margin-top: 1rem;">
        <span style="background: rgba(76,175,80,0.2); padding: 0.25rem 0.75rem; border-radius: 15px; color: white; font-size: 0.9rem;">
            ✨ AI-Powered for Students
        </span>
    </div>
</div>
""", unsafe_allow_html=True)


with st.sidebar:
    # User info and logout
    st.markdown(f"""
    <div class="glass-container" style="text-align: center; margin-bottom: 1rem;">
        <p style="color: #4CAF50; font-size: 1.1rem; margin: 0;">👤 {user['full_name'] or user['username']}</p>
        <p style="color: rgba(255,255,255,0.6); font-size: 0.8rem; margin: 0;">{user['email']}</p>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("🚪 Logout", use_container_width=True):
        logout()
        st.rerun()
    
    st.markdown("---")
    
    st.markdown("""
    <div class="glass-container">
        <h2 style="color: white; text-align: center; margin-bottom: 1rem;">⚙️ Settings</h2>
    </div>
    """, unsafe_allow_html=True)

    theme = st.selectbox(
        " .✯. Theme",
        ["Dark Gradient", "Ocean Blue", "Sunset Orange", "Forest Green"],
        index=0
    )

    st.markdown("### 📚 Study Mode Settings")
    
    note_type = st.multiselect(
        "Select Note Sections",
        ["Concept Snapshot", "Core Concepts", "Exam Insights", "Applications", 
         "Common Mistakes", "Smart Keywords", "Active Recall", "Difficulty Level"],
        default=["Concept Snapshot", "Core Concepts", "Exam Insights", "Active Recall"]
    )

    st.markdown("---")
    st.markdown("### ☯ Statistics")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Study Materials", len(st.session_state.history))
    with col2:
        st.metric("Success Rate", "98%")

    st.markdown("---")
    st.markdown("""
    <div class="glass-container">
        <h3 style="color: white; margin-bottom: 1rem;">✨ Features</h3>
        <p style="color: rgba(255,255,255,0.8); line-height: 1.6;">
            Generate comprehensive exam study materials from lectures and PDFs.
        </p>
        <div style="margin-top: 1rem;">
            <span style="color: #4CAF50;">✓</span> Concept Snapshots<br>
            <span style="color: #4CAF50;">✓</span> Core Concepts Breakdown<br>
            <span style="color: #4CAF50;">✓</span> Exam-Focused Insights<br>
            <span style="color: #4CAF50;">✓</span> Real-World Applications<br>
            <span style="color: #4CAF50;">✓</span> Common Mistakes<br>
            <span style="color: #4CAF50;">✓</span> Smart Keywords<br>
            <span style="color: #4CAF50;">✓</span> Active Recall (MCQ, T/F, Fill-in)<br>
            <span style="color: #4CAF50;">✓</span> Difficulty Assessment
        </div>
    </div>
    """, unsafe_allow_html=True)


tab1, tab2, tab3 = st.tabs(["📚 Generate Notes", "📖 Study History", "📊 Analytics"])


with tab1:
    st.markdown("### 💾 Export Format")
    export_format = st.radio("Select Output Format:", ["PDF", "Markdown", "Word"], horizontal=True)
    
    st.markdown("---")
    st.markdown("### ✧ Choose Your Input Method")
    col1, col2 = st.columns(2)

    with col1:
        mic_clicked = st.button("♬ Microphone", key="mic_btn", use_container_width=True)
        if mic_clicked:
            st.session_state.input_method = "mic"
    with col2:
        file_clicked = st.button("𓆰 File Upload", key="file_btn", use_container_width=True)
        if file_clicked:
            st.session_state.input_method = "file"

    if 'input_method' in st.session_state:
        st.markdown(f"<div class='glass-container fade-in'>", unsafe_allow_html=True)
        if st.session_state.input_method == "mic":
            st.markdown("### ♨ Microphone Recording")
            duration = st.slider("Recording Duration (minutes)", 0.5, 30.0, 5.0, 0.5)
            if st.button("❃ Start Recording"):
                st.session_state.processing = True
                with st.spinner("Recording..."):
                    progress_bar = st.progress(0)
                    for i in range(100):
                        progress_bar.progress(i + 1)
                        time.sleep(duration * 60 / 100)
                    result = process_input(source_type="mic", duration=int(duration * 60), export_format=export_format)
                    st.session_state.current_result = result
                    st.session_state.processing = False

        elif st.session_state.input_method == "file":
            st.markdown("### ✉ File Upload")
            uploaded_file = st.file_uploader("Upload Audio, Video, or PDF", type=["wav", "mp3", "m4a", "mp4", "avi", "mov", "pdf"])
            if uploaded_file:
                st.markdown("### ☏ File Preview")
                st.info(f"File: {uploaded_file.name}")
                
                # Handle PDF preview
                if uploaded_file.type == "application/pdf":
                    st.success("✓ PDF file selected for text extraction")
                # Handle audio preview
                elif uploaded_file.type.startswith('audio'):
                    st.audio(uploaded_file)
                # Handle video preview
                elif uploaded_file.type.startswith('video'):
                    st.video(uploaded_file)

                if st.button("✈ Process File"):
                    st.session_state.processing = True
                    file_path = f"temp_{uploaded_file.name}"
                    
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getvalue())
                    
                    try:
                        with st.spinner("Processing file..."):
                            # Handle PDF files
                            if uploaded_file.type == "application/pdf":
                                try:
                                    pdf_text = process_pdf(file_path)
                                    result = process_input(source_type="pdf", pdf_text=pdf_text, export_format=export_format)
                                except RuntimeError as e:
                                    st.error(f"⚠️ PDF processing error: {str(e)}")
                                    result = {"error": str(e)}
                            else:
                                # Handle audio/video files
                                result = process_input(source_type="file", file_path=file_path, export_format=export_format)
                            
                            st.session_state.current_result = result
                    except Exception as e:
                        st.error(f"❌ Error processing file: {str(e)}")
                        result = {"error": str(e)}
                        st.session_state.current_result = result
                    finally:
                        st.session_state.processing = False
                        if os.path.exists(file_path):
                            os.remove(file_path)

        st.markdown("</div>", unsafe_allow_html=True)


if st.session_state.current_result:
    result = st.session_state.current_result
    if "error" in result:
        st.error(f"✘ Error: {result['error']}")
    else:
        st.markdown("""
        <div class="results-header fade-in">
            <div class="results-title">✅ Study Notes Generated Successfully!</div>
            <div style="color: rgba(255,255,255,0.8);">Your smart exam study materials are ready</div>
        </div>
        """, unsafe_allow_html=True)

        # Search functionality
        search_term = st.text_input("🔍 Search in notes:", placeholder="Enter keyword to search...")
        
        # =============================================
        # 📊 8. Difficulty Level Indicator (shown first)
        # =============================================
        difficulty = result.get('difficulty', {})
        if difficulty:
            level = difficulty.get('level', 'moderate')
            icons = {"easy": "🟢", "moderate": "🟡", "advanced": "🔴"}
            colors = {"easy": "#4CAF50", "moderate": "#FF9800", "advanced": "#F44336"}
            icon = icons.get(level, "⚪")
            color = colors.get(level, "#999")
            
            st.markdown(f"""
            <div class="glass-container" style="border-left: 4px solid {color};">
                <h3>{icon} Difficulty Level: {difficulty.get('label', 'N/A')} — Score: {difficulty.get('score', 0)}/100</h3>
                <p style="color: rgba(255,255,255,0.85);">{difficulty.get('description', '')}</p>
                <div style="margin-top: 0.5rem; font-size: 0.85rem; color: rgba(255,255,255,0.6);">
                    Words: {difficulty.get('stats', {}).get('total_words', 0)} | 
                    Avg word length: {difficulty.get('stats', {}).get('avg_word_length', 0)} | 
                    Technical terms: {difficulty.get('stats', {}).get('technical_terms', 0)}
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        # =============================================
        # 🧠 1. Concept Snapshot
        # =============================================
        with st.expander("🧠 1. Concept Snapshot — Understand in 2 Minutes", expanded=True):
            snapshot = result.get('concept_snapshot', {})
            if snapshot:
                st.markdown("#### 💡 What is this topic?")
                what_text = snapshot.get('what', 'N/A')
                if search_term and search_term.lower() in what_text.lower():
                    what_text = what_text.replace(search_term, f"**{search_term}**")
                st.markdown(f"<div class='glass-container'><p>{what_text}</p></div>", unsafe_allow_html=True)
                
                st.markdown("#### ❓ Why is it important?")
                why_text = snapshot.get('why', 'N/A')
                if search_term and search_term.lower() in why_text.lower():
                    why_text = why_text.replace(search_term, f"**{search_term}**")
                st.markdown(f"<div class='glass-container'><p>{why_text}</p></div>", unsafe_allow_html=True)
                
                st.markdown("#### 🌍 Where is it used?")
                where_text = snapshot.get('where', 'N/A')
                if search_term and search_term.lower() in where_text.lower():
                    where_text = where_text.replace(search_term, f"**{search_term}**")
                st.markdown(f"<div class='glass-container'><p>{where_text}</p></div>", unsafe_allow_html=True)
            else:
                st.info("Concept snapshot not available")
        
        # =============================================
        # 🏗️ 2. Core Concepts Breakdown
        # =============================================
        with st.expander("🏗️ 2. Core Concepts Breakdown"):
            core = result.get('core_concepts', {})
            if core:
                if core.get('definitions'):
                    st.markdown("#### 📖 Definitions")
                    for d in core['definitions']:
                        text = d
                        if search_term and search_term.lower() in text.lower():
                            text = text.replace(search_term, f"**{search_term}**")
                        st.markdown(f"- {text}")
                
                if core.get('formulas'):
                    st.markdown("#### 🔢 Important Formulas")
                    for f_item in core['formulas']:
                        text = f_item
                        if search_term and search_term.lower() in text.lower():
                            text = text.replace(search_term, f"**{search_term}**")
                        st.markdown(f"- {text}")
                
                if core.get('mechanisms'):
                    st.markdown("#### ⚙️ Key Mechanisms & Principles")
                    for m in core['mechanisms']:
                        text = m
                        if search_term and search_term.lower() in text.lower():
                            text = text.replace(search_term, f"**{search_term}**")
                        st.markdown(f"- {text}")
                
                if core.get('processes'):
                    st.markdown("#### 📋 Step-by-Step Processes")
                    for p in core['processes']:
                        text = p
                        if search_term and search_term.lower() in text.lower():
                            text = text.replace(search_term, f"**{search_term}**")
                        st.markdown(f"- {text}")
            else:
                st.info("Core concepts not available")
        
        # =============================================
        # 🎯 3. Exam-Focused Insights
        # =============================================
        with st.expander("🎯 3. Exam-Focused Insights"):
            exam = result.get('exam_insights', {})
            if exam:
                if exam.get('faq_points'):
                    st.markdown("#### 🔥 Frequently Asked Points")
                    for faq in exam['faq_points']:
                        st.markdown(f"- {faq}")
                
                if exam.get('short_answers'):
                    st.markdown("#### ✏️ 2-Mark Answer Points")
                    for sa in exam['short_answers']:
                        st.markdown(f"- {sa}")
                
                if exam.get('long_answers'):
                    st.markdown("#### 📝 5-Mark Answer Format")
                    for i, la in enumerate(exam['long_answers'], 1):
                        st.markdown(f"**Answer {i}:** {la}")
                        st.markdown("---")
                
                if exam.get('tricky_areas'):
                    st.markdown("#### ⚠️ Tricky Areas — Where Students Go Wrong")
                    for t in exam['tricky_areas']:
                        st.warning(f"⚠️ {t}")
            else:
                st.info("Exam insights not available")
        
        # =============================================
        # 🧩 4. Real-World Applications
        # =============================================
        with st.expander("🧩 4. Real-World Applications"):
            apps = result.get('applications', [])
            if apps:
                for app in apps:
                    text = app
                    if search_term and search_term.lower() in text.lower():
                        text = text.replace(search_term, f"**{search_term}**")
                    st.markdown(f"- 🔹 {text}")
            else:
                st.info("Applications not available")
        
        # =============================================
        # ⚠️ 5. Common Mistakes & Confusions
        # =============================================
        with st.expander("⚠️ 5. Common Mistakes & Confusions"):
            mistakes = result.get('common_mistakes', [])
            if mistakes:
                for m in mistakes:
                    st.markdown(f"<div class='glass-container' style='border-left: 3px solid #F44336; margin-bottom: 0.5rem;'><p>❌ {m}</p></div>", unsafe_allow_html=True)
            else:
                st.info("No common mistakes identified")
        
        # =============================================
        # 🔑 6. Smart Keywords + Definitions
        # =============================================
        with st.expander("🔑 6. Smart Keywords + Definitions"):
            smart_kw = result.get('smart_keywords', [])
            if smart_kw:
                if search_term:
                    smart_kw = [kw for kw in smart_kw if search_term.lower() in kw['term'].lower() or search_term.lower() in kw['meaning'].lower()]
                
                for kw in smart_kw:
                    st.markdown(f"""
                    <div class='glass-container' style='margin-bottom: 0.5rem;'>
                        <h4 style='color: #4CAF50; margin: 0;'>{kw['term']}</h4>
                        <p style='margin: 0.3rem 0;'><strong>Meaning:</strong> {kw['meaning'][:200]}</p>
                        <p style='margin: 0; color: #FF9800; font-style: italic;'>💡 {kw['trick']}</p>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("Smart keywords not available")
        
        # =============================================
        # 🃏 7. Active Recall Mode
        # =============================================
        with st.expander("🃏 7. Active Recall Mode — Exam Training"):
            recall = result.get('active_recall', {})
            if recall:
                recall_tab1, recall_tab2, recall_tab3, recall_tab4 = st.tabs(
                    ["❓ Q&A Cards", "📝 MCQs", "✅ True/False", "📝 Fill Blanks"]
                )
                
                with recall_tab1:
                    qa_cards = recall.get('qa_cards', [])
                    if search_term:
                        qa_cards = [c for c in qa_cards if search_term.lower() in c['question'].lower() or search_term.lower() in c['answer'].lower()]
                    if qa_cards:
                        for i, card in enumerate(qa_cards, 1):
                            st.markdown(f"<div class='glass-container'>", unsafe_allow_html=True)
                            st.markdown(f"**Q{i}: {card['question']}**")
                            if st.checkbox(f"Show Answer", key=f"qa_{i}"):
                                st.success(f"✅ {card['answer']}")
                            st.markdown("</div>", unsafe_allow_html=True)
                    else:
                        st.info("No Q&A cards available")
                
                with recall_tab2:
                    mcqs = recall.get('mcqs', [])
                    if mcqs:
                        for i, mcq in enumerate(mcqs, 1):
                            st.markdown(f"**Q{i}: {mcq['question']}**")
                            user_answer = st.radio(
                                f"Select answer for Q{i}:",
                                mcq['options'],
                                key=f"mcq_{i}",
                                index=None
                            )
                            if user_answer:
                                if user_answer == mcq['answer']:
                                    st.success("✅ Correct!")
                                else:
                                    st.error(f"❌ Wrong! Correct answer: {mcq['answer']}")
                            st.markdown("---")
                    else:
                        st.info("No MCQs available")
                
                with recall_tab3:
                    tf_cards = recall.get('true_false', [])
                    if tf_cards:
                        for i, tf in enumerate(tf_cards, 1):
                            st.markdown(f"**{i}. {tf['statement']}**")
                            user_tf = st.radio(
                                f"True or False? (Q{i})",
                                ["True", "False"],
                                key=f"tf_{i}",
                                index=None
                            )
                            if user_tf:
                                correct = "True" if tf['answer'] else "False"
                                if user_tf == correct:
                                    st.success("✅ Correct!")
                                else:
                                    st.error(f"❌ Wrong! Answer: {correct}")
                            st.markdown("---")
                    else:
                        st.info("No True/False questions available")
                
                with recall_tab4:
                    fill_cards = recall.get('fill_blanks', [])
                    if fill_cards:
                        for i, fb in enumerate(fill_cards, 1):
                            st.markdown(f"**{i}. {fb['question']}**")
                            user_fill = st.text_input(f"Your answer:", key=f"fill_{i}")
                            if user_fill:
                                if user_fill.lower().strip() == fb['answer'].lower().strip():
                                    st.success("✅ Correct!")
                                else:
                                    st.error(f"❌ Correct answer: {fb['answer']}")
                            st.markdown("---")
                    else:
                        st.info("No fill-in-the-blank questions available")
            else:
                st.info("Active recall not available")

        # Download Section
        st.markdown("---")
        st.markdown("### 💾 Download Study Materials")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if result.get("output_file") and os.path.exists(result["output_file"]):
                with open(result["output_file"], "rb") as f:
                    file_label = "📄 PDF" if result["output_file"].endswith('.pdf') else "📝 Markdown" if result["output_file"].endswith('.md') else "📄 Document"
                    st.download_button(
                        f"Download {file_label}",
                        f.read(),
                        file_name=result["output_file"],
                        mime="application/octet-stream",
                        use_container_width=True
                    )
        
        with col2:
            alt_format = st.selectbox("Convert to:", ["PDF", "Markdown", "Word"])
            if st.button("Convert & Download", use_container_width=True):
                with st.spinner(f"Converting to {alt_format}..."):
                    try:
                        from lecture_processor import export_to_pdf, export_to_markdown, export_to_word
                        
                        if alt_format == "PDF":
                            new_file = export_to_pdf(result)
                        elif alt_format == "Markdown":
                            new_file = export_to_markdown(result)
                        else:
                            new_file = export_to_word(result)
                        
                        if os.path.exists(new_file):
                            with open(new_file, "rb") as f:
                                st.download_button(
                                    f"📥 Download {alt_format}",
                                    f.read(),
                                    file_name=new_file,
                                    mime="application/octet-stream",
                                    use_container_width=True,
                                    key="converted_file"
                                )
                    except Exception as e:
                        st.error(f"Conversion error: {str(e)}")

        if result not in st.session_state.history:
            st.session_state.history.append({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "result": result,
                "type": st.session_state.get('input_method', 'unknown')
            })


with tab2:
    st.markdown("### 📖 Study Materials History")
    if st.session_state.history:
        for i, item in enumerate(reversed(st.session_state.history)):
            with st.expander(f"📚 Study Session {len(st.session_state.history) - i} - {item['timestamp']}"):
                st.markdown(f"**Input Type:** {item['type'].title()}")
                
                # Show concept snapshot
                snapshot = item['result'].get('concept_snapshot', {})
                if snapshot and snapshot.get('what'):
                    st.markdown(f"**Concept:** {snapshot['what'][:200]}...")
                
                # Show difficulty
                diff = item['result'].get('difficulty', {})
                if diff:
                    icons = {"easy": "🟢", "moderate": "🟡", "advanced": "🔴"}
                    st.markdown(f"**Difficulty:** {icons.get(diff.get('level',''), '⚪')} {diff.get('label', 'N/A')}")
                
                # Show smart keyword count
                smart_kw = item['result'].get('smart_keywords', [])
                if smart_kw:
                    st.markdown(f"**Smart Keywords:** {len(smart_kw)}")
                
                # Show active recall count
                recall = item['result'].get('active_recall', {})
                if recall:
                    total_q = (len(recall.get('qa_cards', [])) + len(recall.get('mcqs', [])) + 
                              len(recall.get('true_false', [])) + len(recall.get('fill_blanks', [])))
                    st.markdown(f"**Active Recall Questions:** {total_q}")
                
                if st.button(f"View Full Notes {len(st.session_state.history) - i}", key=f"view_{i}"):
                    st.session_state.current_result = item['result']
                    st.rerun()
    else:
        st.info("No study materials yet. Start creating your first set of notes!")


with tab3:
    st.markdown("### 📊 Study Analytics Dashboard")
    col1, col2, col3, col4 = st.columns(4)
    with col1: 
        st.metric("Study Materials", len(st.session_state.history), "📚")
    with col2: 
        total_recall = sum(
            len(item['result'].get('active_recall', {}).get('qa_cards', [])) +
            len(item['result'].get('active_recall', {}).get('mcqs', [])) +
            len(item['result'].get('active_recall', {}).get('true_false', [])) +
            len(item['result'].get('active_recall', {}).get('fill_blanks', []))
            for item in st.session_state.history
        )
        st.metric("Total Questions", total_recall, "🃏")
    with col3: 
        total_keywords = sum(len(item['result'].get('smart_keywords', [])) for item in st.session_state.history)
        st.metric("Smart Keywords", total_keywords, "🔑")
    with col4: 
        if st.session_state.history:
            avg_diff = sum(item['result'].get('difficulty', {}).get('score', 0) for item in st.session_state.history) / len(st.session_state.history)
            st.metric("Avg Difficulty", f"{avg_diff:.0f}/100", "📊")
        else:
            st.metric("Avg Difficulty", "N/A", "📊")
    
    st.markdown("---")
    st.markdown("### 📈 Study Progress")
    st.info("💡 Tip: Use Active Recall Mode regularly — it improves retention by 80%!")
    
    if st.session_state.history:
        st.markdown("**Recent Study Sessions:**")
        for i, item in enumerate(st.session_state.history[-5:], 1):
            diff = item['result'].get('difficulty', {})
            icons = {"easy": "🟢", "moderate": "🟡", "advanced": "🔴"}
            icon = icons.get(diff.get('level', ''), '⚪')
            st.markdown(f"{i}. {icon} {item['type'].title()} - {item['timestamp']}")


st.markdown("""
<div class="custom-footer">
    <p><strong>📚 Exam Study Notes Generator</strong> • v3.0</p>
    <p>Empowering students with AI-powered study materials</p>
    <p style="font-size: 0.9rem; margin-top: 0.5rem;">
        Built with ♡ for Students • © 2025
    </p>
</div>
""", unsafe_allow_html=True)
