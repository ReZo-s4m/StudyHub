import os
import json
import whisper
import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write
from transformers import pipeline
from fpdf import FPDF
from docx import Document
import pdfplumber
import PyPDF2
import re
import random
from collections import Counter
from datetime import datetime
try:
    import pytesseract
    from PIL import Image
    import io
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


samplerate = 44100
summarizer_pipeline = pipeline("summarization", model="google/flan-t5-base")

def record_audio(duration=5, filename="mic_output.wav", stop_event=None):
    print("☥ Recording Started...")
    try:
        chunks = []

        def callback(indata, frames, time_info, status):
            if status:
                print(f"Audio stream status: {status}")
            chunks.append(indata.copy())

        with sd.InputStream(
            samplerate=samplerate,
            channels=1,
            dtype='float32',
            callback=callback,
        ):
            elapsed_ms = 0
            target_ms = int(duration * 1000)
            while elapsed_ms < target_ms:
                if stop_event is not None and stop_event.is_set():
                    print("⏹ Recording stopped by user")
                    return None
                sd.sleep(100)
                elapsed_ms += 100

        if not chunks:
            return None

        audio = np.concatenate(chunks, axis=0)
        write(filename, samplerate, (audio * 32767).astype('int16'))
        print("↪ Recording Saved as", filename)
        return filename
    except Exception as e:
        print("𒉽 Error while recording:", e)
        return None


def transcribe_audio(file_path):
    try:
        model = whisper.load_model("medium")
        result = model.transcribe(file_path)
        return result["text"]
    except Exception as e:
        raise RuntimeError(f"Transcription failed: {str(e)}")

def sanitize_text_for_pdf(text):
    """Sanitize text to handle Unicode characters that FPDF can't encode"""
    if not text:
        return text
    
    # Common Unicode character replacements
    replacements = {
        '\u2013': '-',      # en-dash → hyphen
        '\u2014': '--',     # em-dash → double hyphen
        '\u2018': "'",     # left single quote → apostrophe
        '\u2019': "'",     # right single quote → apostrophe
        '\u201C': '"',     # left double quote → double quote
        '\u201D': '"',     # right double quote → double quote
        '\u2022': '*',      # bullet → asterisk
        '\u2026': '...',    # ellipsis → three dots
        '\xad': '',         # soft hyphen → remove
    }
    
    for unicode_char, replacement in replacements.items():
        text = text.replace(unicode_char, replacement)
    
    # Encode to latin-1 then back to handle any remaining problematic characters
    try:
        text = text.encode('latin-1', errors='ignore').decode('latin-1')
    except Exception as e:
        print(f"Warning: Could not sanitize text fully: {e}")
    
    return text


def extract_text_from_pdf(file_path):
    """Extract text from PDF using pdfplumber or PyPDF2"""
    text = ""
    try:
        # Try pdfplumber first (better for most PDFs)
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text.strip() if text.strip() else None
    except Exception as e:
        print(f"pdfplumber extraction failed: {e}. Trying PyPDF2...")
        try:
            # Fallback to PyPDF2
            with open(file_path, 'rb') as pdf_file:
                reader = PyPDF2.PdfReader(pdf_file)
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            return text.strip() if text.strip() else None
        except Exception as e:
            print(f"PyPDF2 extraction also failed: {e}")
            return None


def extract_text_with_ocr(file_path):
    """Extract text from PDF using OCR (pytesseract) as fallback"""
    if not HAS_OCR:
        raise RuntimeError(
            "OCR not available. Please install pytesseract and set TESSDATA_PREFIX environment variable. "
            "Visit: https://github.com/UB-Mannheim/tesseract/wiki"
        )
    
    try:
        print("🔍 Attempting OCR on PDF...")
        text = ""
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                # Convert page to image for OCR
                try:
                    image = page.to_image(resolution=300)
                    # Get PIL Image from pdfplumber image object
                    if hasattr(image, 'original'):
                        pil_image = image.original
                    else:
                        pil_image = Image.new('RGB', (image.width, image.height))
                    
                    page_text = pytesseract.image_to_string(pil_image)
                    if page_text.strip():
                        text += f"[Page {page_num}]\n{page_text}\n"
                except Exception as page_error:
                    print(f"OCR failed on page {page_num}: {page_error}")
                    continue
        
        return text.strip() if text.strip() else None
    except Exception as e:
        raise RuntimeError(f"OCR extraction failed: {str(e)}")


def process_pdf(file_path):
    """Extract text from PDF using multiple methods"""
    try:
        # First try standard text extraction
        text = extract_text_from_pdf(file_path)
        
        if text and len(text.strip()) > 50:
            print("✓ Text extracted successfully")
            return text
        
        # If no text or minimal text, try OCR
        print("⚠ Limited text found. Attempting OCR...")
        ocr_text = extract_text_with_ocr(file_path)
        if ocr_text and len(ocr_text.strip()) > 50:
            print("✓ Text extracted via OCR")
            return ocr_text
        
        raise RuntimeError(
            "Could not extract text from PDF. The file may be empty, corrupted, or contain only images. "
            "Ensure Tesseract OCR is installed if using image-based PDFs."
        )
    except Exception as e:
        raise RuntimeError(f"PDF processing failed: {str(e)}")


def chunk_text(text, max_words=1000):
    sentences = text.split('. ')
    chunks = []
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk.split()) + len(sentence.split()) < max_words:
            current_chunk += sentence + ". "
        else:
            chunks.append(current_chunk.strip())
            current_chunk = sentence + ". "
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks


def clean_and_organize_text(text):
    """Clean and organize extracted text for better readability"""
    if not text:
        return text
    
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Fix common OCR errors
    text = re.sub(r'(\w)-\s+(\w)', r'\1\2', text)  # Fix hyphenated words
    
    # Organize into paragraphs based on sentence endings
    sentences = re.split(r'([.!?])\s+', text)
    organized = ""
    for i in range(0, len(sentences)-1, 2):
        if i+1 < len(sentences):
            organized += sentences[i] + sentences[i+1] + " "
        if (i // 2 + 1) % 5 == 0:  # New paragraph every 5 sentences
            organized += "\n\n"
    
    return organized.strip()


def extract_main_topics(text):
    """Extract main topics from text using AI"""
    try:
        chunks = chunk_text(text, max_words=500)
        topics = []
        
        for chunk in chunks[:3]:
            result = summarizer_pipeline(
                "Identify the main topic:\n\n" + chunk,
                max_length=50,
                min_length=10,
                do_sample=False
            )[0]['summary_text']
            topics.append(result.strip())
        
        return list(set(topics))
    except Exception as e:
        print(f"Topic extraction error: {e}")
        return ["General Content"]


def extract_keywords(text):
    """Extract important keywords for revision"""
    stop_words = set(['the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                      'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
                      'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                      'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those',
                      'also', 'more', 'such', 'than', 'other', 'some', 'only', 'into', 'over',
                      'after', 'before', 'between', 'each', 'every', 'both', 'through', 'during',
                      'about', 'very', 'when', 'where', 'which', 'while', 'what', 'there', 'then',
                      'them', 'they', 'their', 'been', 'being', 'most', 'same', 'just', 'because'])
    
    words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
    filtered_words = [word for word in words if word not in stop_words]
    word_counts = Counter(filtered_words)
    keywords = [word for word, count in word_counts.most_common(30) if count > 1]
    return keywords[:20]


# ============================================================
# SECTION 1: Concept Snapshot
# ============================================================
def generate_concept_snapshot(text):
    """Generate a beginner-friendly concept snapshot explaining what, why, and where."""
    try:
        preview = text[:4000] if len(text) > 4000 else text
        chunks = chunk_text(preview, max_words=800)
        
        # What is this topic?
        what_result = summarizer_pipeline(
            "Explain what this topic is about in simple language a beginner can understand:\n\n" + chunks[0],
            max_length=300,
            min_length=60,
            do_sample=False
        )[0]['summary_text']
        
        # Why is it important?
        why_result = summarizer_pipeline(
            "Explain why this topic is important and why students should learn it:\n\n" + chunks[0],
            max_length=250,
            min_length=40,
            do_sample=False
        )[0]['summary_text']
        
        # Where is it used?
        where_result = summarizer_pipeline(
            "Explain where and how this topic is used or applied:\n\n" + chunks[0],
            max_length=250,
            min_length=40,
            do_sample=False
        )[0]['summary_text']
        
        snapshot = {
            "what": what_result.strip(),
            "why": why_result.strip(),
            "where": where_result.strip()
        }
        return snapshot
    except Exception as e:
        print(f"Concept snapshot error: {e}")
        return {
            "what": text[:300] + "...",
            "why": "Important for academic understanding.",
            "where": "Used across various domains."
        }


# ============================================================
# SECTION 2: Core Concepts Breakdown
# ============================================================
def generate_core_concepts(text):
    """Generate structured breakdown: definitions, formulas, key mechanisms, processes."""
    chunks = chunk_text(text, max_words=600)
    
    definitions = []
    formulas = []
    mechanisms = []
    processes = []
    
    sentences = re.split(r'[.!?]+', text)
    
    # Extract definitions
    for sentence in sentences:
        sentence = sentence.strip()
        if re.search(r'\b(is defined as|is|are|means|refers to|known as)\b', sentence, re.IGNORECASE):
            if 20 < len(sentence) < 300:
                definitions.append(sentence)
    
    # Extract formulas / equations
    for sentence in sentences:
        sentence = sentence.strip()
        if re.search(r'[=+\-*/^]|formula|equation|expression', sentence, re.IGNORECASE):
            if 10 < len(sentence) < 300:
                formulas.append(sentence)
    
    # Use AI for key mechanisms and processes
    for chunk in chunks:
        try:
            mech = summarizer_pipeline(
                "List the key mechanisms, principles, and important concepts:\n\n" + chunk,
                max_length=400,
                min_length=50,
                do_sample=False
            )[0]['summary_text']
            for s in re.split(r'[.!?]+', mech):
                s = s.strip()
                if s and len(s) > 15:
                    mechanisms.append(s)
        except Exception as e:
            print(f"Core concepts mechanisms error: {e}")
            continue
        
        try:
            proc = summarizer_pipeline(
                "List step-by-step processes and methods described:\n\n" + chunk,
                max_length=400,
                min_length=50,
                do_sample=False
            )[0]['summary_text']
            for s in re.split(r'[.!?]+', proc):
                s = s.strip()
                if s and len(s) > 15:
                    processes.append(s)
        except Exception as e:
            print(f"Core concepts processes error: {e}")
            continue
    
    # Remove duplicates while preserving order
    definitions = list(dict.fromkeys(definitions))[:15]
    formulas = list(dict.fromkeys(formulas))[:10]
    mechanisms = list(dict.fromkeys(mechanisms))[:15]
    processes = list(dict.fromkeys(processes))[:10]
    
    return {
        "definitions": definitions,
        "formulas": formulas,
        "mechanisms": mechanisms,
        "processes": processes
    }


# ============================================================
# SECTION 3: Exam-Focused Insights
# ============================================================
def generate_exam_insights(text):
    """Generate exam-focused content: FAQ points, short/long answer format, tricky areas."""
    chunks = chunk_text(text, max_words=600)
    
    faq_points = []
    short_answers = []
    long_answers = []
    tricky_areas = []
    
    for chunk in chunks:
        # Frequently asked / important points
        try:
            faq = summarizer_pipeline(
                "What are the most frequently asked exam questions from this content:\n\n" + chunk,
                max_length=400,
                min_length=50,
                do_sample=False
            )[0]['summary_text']
            for s in re.split(r'[.!?]+', faq):
                s = s.strip()
                if s and len(s) > 15:
                    faq_points.append(s)
        except Exception as e:
            print(f"FAQ error: {e}")
        
        # Short answer format (2-mark style)
        try:
            short = summarizer_pipeline(
                "Create brief 2-mark exam answers from this content:\n\n" + chunk,
                max_length=300,
                min_length=40,
                do_sample=False
            )[0]['summary_text']
            for s in re.split(r'[.!?]+', short):
                s = s.strip()
                if s and len(s) > 15:
                    short_answers.append(s)
        except Exception as e:
            print(f"Short answer error: {e}")
        
        # Long answer format (5-mark style)
        try:
            long_ans = summarizer_pipeline(
                "Create a detailed 5-mark exam answer from this content:\n\n" + chunk,
                max_length=450,
                min_length=80,
                do_sample=False
            )[0]['summary_text']
            long_answers.append(long_ans.strip())
        except Exception as e:
            print(f"Long answer error: {e}")
        
        # Tricky areas
        try:
            tricky = summarizer_pipeline(
                "What are confusing or tricky parts students might get wrong:\n\n" + chunk,
                max_length=300,
                min_length=30,
                do_sample=False
            )[0]['summary_text']
            for s in re.split(r'[.!?]+', tricky):
                s = s.strip()
                if s and len(s) > 15:
                    tricky_areas.append(s)
        except Exception as e:
            print(f"Tricky areas error: {e}")
    
    faq_points = list(dict.fromkeys(faq_points))[:15]
    short_answers = list(dict.fromkeys(short_answers))[:10]
    long_answers = list(dict.fromkeys(long_answers))[:5]
    tricky_areas = list(dict.fromkeys(tricky_areas))[:10]
    
    return {
        "faq_points": faq_points,
        "short_answers": short_answers,
        "long_answers": long_answers,
        "tricky_areas": tricky_areas
    }


# ============================================================
# SECTION 4: Real-World Applications
# ============================================================
def generate_real_world_applications(text):
    """Generate real-world applications, industry examples, case studies."""
    chunks = chunk_text(text, max_words=800)
    applications = []
    
    for chunk in chunks:
        try:
            result = summarizer_pipeline(
                "Describe real-world applications, industry uses, and practical examples of these concepts:\n\n" + chunk,
                max_length=400,
                min_length=50,
                do_sample=False
            )[0]['summary_text']
            for s in re.split(r'[.!?]+', result):
                s = s.strip()
                if s and len(s) > 15:
                    applications.append(s)
        except Exception as e:
            print(f"Applications error: {e}")
            continue
    
    # Also extract from text directly
    sentences = re.split(r'[.!?]+', text)
    app_patterns = ['used in', 'application', 'applied', 'industry', 'real world',
                    'practical', 'example', 'case study', 'implemented', 'deployed',
                    'company', 'organization', 'system', 'technology', 'software']
    
    for sentence in sentences:
        sentence = sentence.strip()
        if any(pat in sentence.lower() for pat in app_patterns) and 25 < len(sentence) < 300:
            if sentence not in applications:
                applications.append(sentence)
    
    return list(dict.fromkeys(applications))[:15]


# ============================================================
# SECTION 5: Common Mistakes & Confusions
# ============================================================
def generate_common_mistakes(text):
    """Generate common mistakes, confusions, and important assumptions."""
    chunks = chunk_text(text, max_words=800)
    mistakes = []
    
    for chunk in chunks:
        try:
            result = summarizer_pipeline(
                "What common mistakes, confusions, and wrong assumptions do students make about this:\n\n" + chunk,
                max_length=400,
                min_length=40,
                do_sample=False
            )[0]['summary_text']
            for s in re.split(r'[.!?]+', result):
                s = s.strip()
                if s and len(s) > 15:
                    mistakes.append(s)
        except Exception as e:
            print(f"Common mistakes error: {e}")
            continue
    
    # Extract from text: sentences with warning/confusion patterns
    sentences = re.split(r'[.!?]+', text)
    warn_patterns = ['not', 'don\'t', 'cannot', 'never', 'only when', 'only if', 'except',
                     'however', 'but', 'although', 'unlike', 'different from', 'confused',
                     'mistake', 'error', 'wrong', 'incorrect', 'assumption', 'careful',
                     'note that', 'important to', 'remember', 'warning', 'caution']
    
    for sentence in sentences:
        sentence = sentence.strip()
        if any(pat in sentence.lower() for pat in warn_patterns) and 25 < len(sentence) < 300:
            if sentence not in mistakes:
                mistakes.append(sentence)
    
    return list(dict.fromkeys(mistakes))[:15]


# ============================================================
# SECTION 6: Smart Keywords + Definitions
# ============================================================
def generate_smart_keywords(text):
    """Generate keywords with definitions and memory tricks."""
    keywords = extract_keywords(text)
    sentences = re.split(r'[.!?]+', text)
    
    smart_keywords = []
    for keyword in keywords:
        # Find the best defining sentence
        best_sentence = ""
        for sentence in sentences:
            if keyword.lower() in sentence.lower() and len(sentence) > 20:
                if re.search(r'\b(is|are|means|refers|defined)\b', sentence, re.IGNORECASE):
                    best_sentence = sentence.strip()
                    break
                elif not best_sentence:
                    best_sentence = sentence.strip()
        
        if not best_sentence:
            best_sentence = f"An important concept related to the topic"
        
        # Generate a simple memory trick
        try:
            trick = summarizer_pipeline(
                f"Create a one-line memory trick to remember: {keyword} means {best_sentence[:100]}",
                max_length=60,
                min_length=10,
                do_sample=False
            )[0]['summary_text']
        except Exception:
            trick = f"Remember: {keyword.upper()} = {best_sentence[:50]}"
        
        smart_keywords.append({
            "term": keyword.capitalize(),
            "meaning": best_sentence[:200],
            "trick": trick.strip()
        })
    
    return smart_keywords[:15]


# ============================================================
# SECTION 7: Active Recall Mode (Flashcards 2.0)
# ============================================================
def generate_active_recall(text):
    """Generate advanced flashcards: Q&A, MCQs, True/False, Fill in the blanks."""
    sentences = re.split(r'[.!?]+', text)
    
    qa_cards = []
    mcqs = []
    true_false = []
    fill_blanks = []
    
    # --- Q&A Cards ---
    for sentence in sentences:
        sentence = sentence.strip()
        match = re.search(r'^([^,]+?)\s+(is|are|means|refers to)\s+(.+)$', sentence, re.IGNORECASE)
        if match and 20 < len(sentence) < 250:
            question = f"What {match.group(2)} {match.group(1).strip()}?"
            answer = match.group(3).strip()
            qa_cards.append({"question": question, "answer": answer})
            if len(qa_cards) >= 10:
                break
    
    # Supplement from keywords if needed
    if len(qa_cards) < 5:
        keywords = extract_keywords(text)
        for keyword in keywords[:8]:
            for sentence in sentences:
                if keyword.lower() in sentence.lower() and 30 < len(sentence) < 250:
                    qa_cards.append({
                        "question": f"Explain: {keyword.capitalize()}",
                        "answer": sentence.strip()
                    })
                    break
    
    # --- MCQs ---
    important_sentences = [s.strip() for s in sentences if 30 < len(s.strip()) < 200]
    keywords = extract_keywords(text)
    
    for sentence in important_sentences[:8]:
        # Find a keyword in this sentence to blank out as the correct answer
        for kw in keywords:
            if kw.lower() in sentence.lower():
                question_text = re.sub(re.escape(kw), '________', sentence, count=1, flags=re.IGNORECASE)
                # Generate distractors from other keywords
                distractors = [k.capitalize() for k in keywords if k.lower() != kw.lower()][:3]
                if len(distractors) >= 2:
                    options = distractors[:3] + [kw.capitalize()]
                    random.shuffle(options)
                    mcqs.append({
                        "question": question_text,
                        "options": options,
                        "answer": kw.capitalize()
                    })
                break
        if len(mcqs) >= 8:
            break
    
    # --- True/False ---
    for sentence in important_sentences[:10]:
        if len(sentence) > 30:
            true_false.append({
                "statement": sentence,
                "answer": True,
                "explanation": "This statement is directly from the study material."
            })
        if len(true_false) >= 6:
            break
    
    # --- Fill in the Blanks ---
    for sentence in important_sentences[:10]:
        for kw in keywords:
            if kw.lower() in sentence.lower() and len(sentence) > 25:
                blanked = re.sub(re.escape(kw), '________', sentence, count=1, flags=re.IGNORECASE)
                if blanked != sentence:
                    fill_blanks.append({
                        "question": blanked,
                        "answer": kw.capitalize()
                    })
                    break
        if len(fill_blanks) >= 8:
            break
    
    return {
        "qa_cards": qa_cards[:10],
        "mcqs": mcqs[:8],
        "true_false": true_false[:6],
        "fill_blanks": fill_blanks[:8]
    }


# ============================================================
# SECTION 8: Difficulty Level Indicator
# ============================================================
def assess_difficulty_level(text):
    """Assess content difficulty based on text complexity metrics."""
    words = text.split()
    total_words = len(words)
    
    # Average word length
    avg_word_len = sum(len(w) for w in words) / max(total_words, 1)
    
    # Long words ratio (words > 8 chars)
    long_words = sum(1 for w in words if len(w) > 8)
    long_ratio = long_words / max(total_words, 1)
    
    # Technical indicators
    tech_patterns = ['algorithm', 'theorem', 'equation', 'derivative', 'integral',
                     'hypothesis', 'methodology', 'paradigm', 'optimization', 'architecture',
                     'computational', 'differential', 'polynomial', 'logarithmic', 'exponential',
                     'regression', 'probability', 'distribution', 'correlation', 'inference',
                     'quantum', 'molecular', 'electromagnetic', 'thermodynamic', 'entropy']
    
    tech_count = sum(1 for word in words if word.lower() in tech_patterns)
    
    # Sentences complexity
    sentences = re.split(r'[.!?]+', text)
    avg_sentence_len = total_words / max(len(sentences), 1)
    
    # Calculate score (0-100)
    score = 0
    score += min(avg_word_len * 5, 25)          # Word complexity (max 25)
    score += min(long_ratio * 100, 25)           # Long words ratio (max 25)
    score += min(tech_count * 3, 25)             # Technical terms (max 25)
    score += min(avg_sentence_len * 0.8, 25)     # Sentence complexity (max 25)
    
    if score < 33:
        level = "easy"
        label = "Easy"
        description = "Beginner-friendly content. Straightforward concepts that are easy to understand and memorize."
    elif score < 66:
        level = "moderate"
        label = "Moderate"
        description = "Intermediate level content. Requires careful reading and practice to fully understand."
    else:
        level = "advanced"
        label = "Advanced"
        description = "Complex material with technical depth. Multiple revisions recommended for exam preparation."
    
    return {
        "level": level,
        "label": label,
        "score": round(score),
        "description": description,
        "stats": {
            "total_words": total_words,
            "avg_word_length": round(avg_word_len, 1),
            "avg_sentence_length": round(avg_sentence_len, 1),
            "technical_terms": tech_count,
            "long_words_pct": round(long_ratio * 100, 1)
        }
    }




def export_to_pdf(result_data):
    """Export comprehensive study notes to PDF"""
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', size=16)
        pdf.cell(200, 10, txt="Exam Study Notes", ln=True, align='C')
        pdf.set_font("Arial", size=10)
        pdf.cell(200, 5, txt="AI-Powered Smart Study Material", ln=True, align='C')
        pdf.ln(5)
        
        # Difficulty indicator
        difficulty = result_data.get('difficulty', {})
        if difficulty:
            level_label = difficulty.get('label', 'N/A')
            pdf.set_font("Arial", "B", size=10)
            pdf.cell(0, 6, f"Difficulty: {level_label} (Score: {difficulty.get('score', 'N/A')}/100)", ln=True)
            pdf.set_font("Arial", size=9)
            pdf.multi_cell(0, 5, sanitize_text_for_pdf(difficulty.get('description', '')))
            pdf.ln(3)
        
        # 1. Concept Snapshot
        snapshot = result_data.get('concept_snapshot', {})
        if snapshot:
            pdf.set_font("Arial", "B", size=13)
            pdf.cell(0, 8, "1. Concept Snapshot", ln=True)
            pdf.set_font("Arial", "B", size=10)
            pdf.cell(0, 6, "What is this topic?", ln=True)
            pdf.set_font("Arial", size=9)
            pdf.multi_cell(0, 5, sanitize_text_for_pdf(snapshot.get('what', '')))
            pdf.ln(2)
            pdf.set_font("Arial", "B", size=10)
            pdf.cell(0, 6, "Why is it important?", ln=True)
            pdf.set_font("Arial", size=9)
            pdf.multi_cell(0, 5, sanitize_text_for_pdf(snapshot.get('why', '')))
            pdf.ln(2)
            pdf.set_font("Arial", "B", size=10)
            pdf.cell(0, 6, "Where is it used?", ln=True)
            pdf.set_font("Arial", size=9)
            pdf.multi_cell(0, 5, sanitize_text_for_pdf(snapshot.get('where', '')))
            pdf.ln(5)
        
        # 2. Core Concepts
        core = result_data.get('core_concepts', {})
        if core:
            pdf.add_page()
            pdf.set_font("Arial", "B", size=13)
            pdf.cell(0, 8, "2. Core Concepts Breakdown", ln=True)
            
            if core.get('definitions'):
                pdf.set_font("Arial", "B", size=10)
                pdf.cell(0, 6, "Definitions:", ln=True)
                pdf.set_font("Arial", size=9)
                for d in core['definitions']:
                    pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"* {d}"))
                pdf.ln(3)
            
            if core.get('formulas'):
                pdf.set_font("Arial", "B", size=10)
                pdf.cell(0, 6, "Important Formulas:", ln=True)
                pdf.set_font("Arial", size=9)
                for f_item in core['formulas']:
                    pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"* {f_item}"))
                pdf.ln(3)
            
            if core.get('mechanisms'):
                pdf.set_font("Arial", "B", size=10)
                pdf.cell(0, 6, "Key Mechanisms & Principles:", ln=True)
                pdf.set_font("Arial", size=9)
                for m in core['mechanisms']:
                    pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"* {m}"))
                pdf.ln(3)
            
            if core.get('processes'):
                pdf.set_font("Arial", "B", size=10)
                pdf.cell(0, 6, "Step-by-Step Processes:", ln=True)
                pdf.set_font("Arial", size=9)
                for p in core['processes']:
                    pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"* {p}"))
                pdf.ln(3)
        
        # 3. Exam-Focused Insights
        exam = result_data.get('exam_insights', {})
        if exam:
            pdf.add_page()
            pdf.set_font("Arial", "B", size=13)
            pdf.cell(0, 8, "3. Exam-Focused Insights", ln=True)
            
            if exam.get('faq_points'):
                pdf.set_font("Arial", "B", size=10)
                pdf.cell(0, 6, "Frequently Asked Points:", ln=True)
                pdf.set_font("Arial", size=9)
                for faq in exam['faq_points']:
                    pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"* {faq}"))
                pdf.ln(3)
            
            if exam.get('short_answers'):
                pdf.set_font("Arial", "B", size=10)
                pdf.cell(0, 6, "2-Mark Answer Points:", ln=True)
                pdf.set_font("Arial", size=9)
                for sa in exam['short_answers']:
                    pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"* {sa}"))
                pdf.ln(3)
            
            if exam.get('long_answers'):
                pdf.set_font("Arial", "B", size=10)
                pdf.cell(0, 6, "5-Mark Answer Format:", ln=True)
                pdf.set_font("Arial", size=9)
                for i, la in enumerate(exam['long_answers'], 1):
                    pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"Answer {i}: {la}"))
                    pdf.ln(2)
                pdf.ln(3)
            
            if exam.get('tricky_areas'):
                pdf.set_font("Arial", "B", size=10)
                pdf.cell(0, 6, "Tricky / Error-prone Areas:", ln=True)
                pdf.set_font("Arial", size=9)
                for t in exam['tricky_areas']:
                    pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"! {t}"))
                pdf.ln(3)
        
        # 4. Real-World Applications
        apps = result_data.get('applications', [])
        if apps:
            pdf.add_page()
            pdf.set_font("Arial", "B", size=13)
            pdf.cell(0, 8, "4. Real-World Applications", ln=True)
            pdf.set_font("Arial", size=9)
            for app in apps:
                pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"* {app}"))
            pdf.ln(3)
        
        # 5. Common Mistakes
        mistakes = result_data.get('common_mistakes', [])
        if mistakes:
            pdf.set_font("Arial", "B", size=13)
            pdf.cell(0, 8, "5. Common Mistakes & Confusions", ln=True)
            pdf.set_font("Arial", size=9)
            for m in mistakes:
                pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"! {m}"))
            pdf.ln(3)
        
        # 6. Smart Keywords
        smart_kw = result_data.get('smart_keywords', [])
        if smart_kw:
            pdf.add_page()
            pdf.set_font("Arial", "B", size=13)
            pdf.cell(0, 8, "6. Smart Keywords + Definitions", ln=True)
            for kw in smart_kw:
                pdf.set_font("Arial", "B", size=10)
                pdf.cell(0, 6, sanitize_text_for_pdf(kw['term']), ln=True)
                pdf.set_font("Arial", size=9)
                pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"Meaning: {kw['meaning']}"))
                pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"Memory Trick: {kw['trick']}"))
                pdf.ln(2)
        
        # 7. Active Recall
        recall = result_data.get('active_recall', {})
        if recall:
            pdf.add_page()
            pdf.set_font("Arial", "B", size=13)
            pdf.cell(0, 8, "7. Active Recall Mode", ln=True)
            
            if recall.get('qa_cards'):
                pdf.set_font("Arial", "B", size=10)
                pdf.cell(0, 6, "Q&A Flashcards:", ln=True)
                for i, card in enumerate(recall['qa_cards'], 1):
                    pdf.set_font("Arial", "B", size=9)
                    pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"Q{i}: {card['question']}"))
                    pdf.set_font("Arial", size=9)
                    pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"A: {card['answer']}"))
                    pdf.ln(2)
            
            if recall.get('mcqs'):
                pdf.set_font("Arial", "B", size=10)
                pdf.cell(0, 6, "Multiple Choice Questions:", ln=True)
                for i, mcq in enumerate(recall['mcqs'], 1):
                    pdf.set_font("Arial", "B", size=9)
                    pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"Q{i}: {mcq['question']}"))
                    pdf.set_font("Arial", size=9)
                    for j, opt in enumerate(mcq['options']):
                        prefix = chr(65 + j)
                        pdf.cell(0, 5, sanitize_text_for_pdf(f"  {prefix}) {opt}"), ln=True)
                    pdf.cell(0, 5, sanitize_text_for_pdf(f"  Answer: {mcq['answer']}"), ln=True)
                    pdf.ln(2)
            
            if recall.get('true_false'):
                pdf.set_font("Arial", "B", size=10)
                pdf.cell(0, 6, "True or False:", ln=True)
                for i, tf in enumerate(recall['true_false'], 1):
                    pdf.set_font("Arial", size=9)
                    ans_text = "True" if tf['answer'] else "False"
                    pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"{i}. {tf['statement']}"))
                    pdf.cell(0, 5, sanitize_text_for_pdf(f"   Answer: {ans_text}"), ln=True)
                    pdf.ln(1)
            
            if recall.get('fill_blanks'):
                pdf.set_font("Arial", "B", size=10)
                pdf.cell(0, 6, "Fill in the Blanks:", ln=True)
                for i, fb in enumerate(recall['fill_blanks'], 1):
                    pdf.set_font("Arial", size=9)
                    pdf.multi_cell(0, 5, sanitize_text_for_pdf(f"{i}. {fb['question']}"))
                    pdf.cell(0, 5, sanitize_text_for_pdf(f"   Answer: {fb['answer']}"), ln=True)
                    pdf.ln(1)
        
        pdf.output("exam_study_notes.pdf")
        print("PDF exported successfully")
        return "exam_study_notes.pdf"
    except Exception as e:
        raise RuntimeError(f"PDF export failed: {str(e)}")


def export_to_markdown(result_data):
    """Export study notes to Markdown format"""
    try:
        md = "# Exam Study Notes\n\n"
        md += "*AI-Powered Smart Study Material*\n\n---\n\n"
        
        # Difficulty
        difficulty = result_data.get('difficulty', {})
        if difficulty:
            icons = {"easy": "🟢", "moderate": "🟡", "advanced": "🔴"}
            icon = icons.get(difficulty.get('level', ''), '⚪')
            md += f"## 📊 Difficulty: {icon} {difficulty.get('label', 'N/A')} (Score: {difficulty.get('score', 'N/A')}/100)\n\n"
            md += f"{difficulty.get('description', '')}\n\n---\n\n"
        
        # 1. Concept Snapshot
        snapshot = result_data.get('concept_snapshot', {})
        if snapshot:
            md += "## 🧠 1. Concept Snapshot\n\n"
            md += f"**What is this topic?**\n{snapshot.get('what', '')}\n\n"
            md += f"**Why is it important?**\n{snapshot.get('why', '')}\n\n"
            md += f"**Where is it used?**\n{snapshot.get('where', '')}\n\n---\n\n"
        
        # 2. Core Concepts
        core = result_data.get('core_concepts', {})
        if core:
            md += "## 🏗️ 2. Core Concepts Breakdown\n\n"
            if core.get('definitions'):
                md += "### Definitions\n"
                for d in core['definitions']:
                    md += f"- {d}\n"
                md += "\n"
            if core.get('formulas'):
                md += "### Important Formulas\n"
                for f_item in core['formulas']:
                    md += f"- {f_item}\n"
                md += "\n"
            if core.get('mechanisms'):
                md += "### Key Mechanisms & Principles\n"
                for m in core['mechanisms']:
                    md += f"- {m}\n"
                md += "\n"
            if core.get('processes'):
                md += "### Step-by-Step Processes\n"
                for p in core['processes']:
                    md += f"- {p}\n"
                md += "\n"
            md += "---\n\n"
        
        # 3. Exam-Focused Insights
        exam = result_data.get('exam_insights', {})
        if exam:
            md += "## 🎯 3. Exam-Focused Insights\n\n"
            if exam.get('faq_points'):
                md += "### Frequently Asked Points\n"
                for faq in exam['faq_points']:
                    md += f"- {faq}\n"
                md += "\n"
            if exam.get('short_answers'):
                md += "### 2-Mark Answer Points\n"
                for sa in exam['short_answers']:
                    md += f"- {sa}\n"
                md += "\n"
            if exam.get('long_answers'):
                md += "### 5-Mark Answer Format\n"
                for i, la in enumerate(exam['long_answers'], 1):
                    md += f"**Answer {i}:** {la}\n\n"
            if exam.get('tricky_areas'):
                md += "### ⚠️ Tricky Areas\n"
                for t in exam['tricky_areas']:
                    md += f"- {t}\n"
                md += "\n"
            md += "---\n\n"
        
        # 4. Applications
        apps = result_data.get('applications', [])
        if apps:
            md += "## 🧩 4. Real-World Applications\n\n"
            for app in apps:
                md += f"- {app}\n"
            md += "\n---\n\n"
        
        # 5. Common Mistakes
        mistakes = result_data.get('common_mistakes', [])
        if mistakes:
            md += "## ⚠️ 5. Common Mistakes & Confusions\n\n"
            for m in mistakes:
                md += f"- {m}\n"
            md += "\n---\n\n"
        
        # 6. Smart Keywords
        smart_kw = result_data.get('smart_keywords', [])
        if smart_kw:
            md += "## 🔑 6. Smart Keywords + Definitions\n\n"
            md += "| Term | Meaning | Memory Trick |\n"
            md += "|------|---------|-------------|\n"
            for kw in smart_kw:
                md += f"| **{kw['term']}** | {kw['meaning'][:80]} | {kw['trick']} |\n"
            md += "\n---\n\n"
        
        # 7. Active Recall
        recall = result_data.get('active_recall', {})
        if recall:
            md += "## 🃏 7. Active Recall Mode\n\n"
            if recall.get('qa_cards'):
                md += "### Q&A Flashcards\n"
                for i, card in enumerate(recall['qa_cards'], 1):
                    md += f"**Q{i}:** {card['question']}\n"
                    md += f"**A:** {card['answer']}\n\n"
            if recall.get('mcqs'):
                md += "### MCQs\n"
                for i, mcq in enumerate(recall['mcqs'], 1):
                    md += f"**Q{i}:** {mcq['question']}\n"
                    for j, opt in enumerate(mcq['options']):
                        md += f"  {chr(65+j)}) {opt}\n"
                    md += f"  **Answer:** {mcq['answer']}\n\n"
            if recall.get('true_false'):
                md += "### True or False\n"
                for i, tf in enumerate(recall['true_false'], 1):
                    ans = "True" if tf['answer'] else "False"
                    md += f"{i}. {tf['statement']} — **{ans}**\n"
                md += "\n"
            if recall.get('fill_blanks'):
                md += "### Fill in the Blanks\n"
                for i, fb in enumerate(recall['fill_blanks'], 1):
                    md += f"{i}. {fb['question']}\n   **Answer:** {fb['answer']}\n\n"
            md += "---\n\n"
        
        md += f"\n*Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n"
        
        with open("exam_study_notes.md", "w", encoding="utf-8") as f:
            f.write(md)
        
        print("Markdown exported successfully")
        return "exam_study_notes.md"
    except Exception as e:
        raise RuntimeError(f"Markdown export failed: {str(e)}")


def export_to_word(result_data):
    """Export comprehensive study notes to Word"""
    try:
        doc = Document()
        title = doc.add_heading("Exam Study Notes", 0)
        title.alignment = 1
        doc.add_paragraph("AI-Powered Smart Study Material").alignment = 1
        
        # Difficulty
        difficulty = result_data.get('difficulty', {})
        if difficulty:
            doc.add_heading(f"Difficulty: {difficulty.get('label', 'N/A')} (Score: {difficulty.get('score', 'N/A')}/100)", level=2)
            doc.add_paragraph(difficulty.get('description', ''))
        
        # 1. Concept Snapshot
        snapshot = result_data.get('concept_snapshot', {})
        if snapshot:
            doc.add_heading("1. Concept Snapshot", level=1)
            doc.add_heading("What is this topic?", level=2)
            doc.add_paragraph(snapshot.get('what', ''))
            doc.add_heading("Why is it important?", level=2)
            doc.add_paragraph(snapshot.get('why', ''))
            doc.add_heading("Where is it used?", level=2)
            doc.add_paragraph(snapshot.get('where', ''))
        
        # 2. Core Concepts
        core = result_data.get('core_concepts', {})
        if core:
            doc.add_page_break()
            doc.add_heading("2. Core Concepts Breakdown", level=1)
            if core.get('definitions'):
                doc.add_heading("Definitions", level=2)
                for d in core['definitions']:
                    doc.add_paragraph(d, style='List Bullet')
            if core.get('formulas'):
                doc.add_heading("Important Formulas", level=2)
                for f_item in core['formulas']:
                    doc.add_paragraph(f_item, style='List Bullet')
            if core.get('mechanisms'):
                doc.add_heading("Key Mechanisms & Principles", level=2)
                for m in core['mechanisms']:
                    doc.add_paragraph(m, style='List Bullet')
            if core.get('processes'):
                doc.add_heading("Step-by-Step Processes", level=2)
                for p in core['processes']:
                    doc.add_paragraph(p, style='List Bullet')
        
        # 3. Exam-Focused Insights
        exam = result_data.get('exam_insights', {})
        if exam:
            doc.add_page_break()
            doc.add_heading("3. Exam-Focused Insights", level=1)
            if exam.get('faq_points'):
                doc.add_heading("Frequently Asked Points", level=2)
                for faq in exam['faq_points']:
                    doc.add_paragraph(faq, style='List Bullet')
            if exam.get('short_answers'):
                doc.add_heading("2-Mark Answer Points", level=2)
                for sa in exam['short_answers']:
                    doc.add_paragraph(sa, style='List Bullet')
            if exam.get('long_answers'):
                doc.add_heading("5-Mark Answer Format", level=2)
                for i, la in enumerate(exam['long_answers'], 1):
                    doc.add_paragraph(f"Answer {i}: {la}")
            if exam.get('tricky_areas'):
                doc.add_heading("Tricky Areas", level=2)
                for t in exam['tricky_areas']:
                    doc.add_paragraph(t, style='List Bullet')
        
        # 4. Applications
        apps = result_data.get('applications', [])
        if apps:
            doc.add_page_break()
            doc.add_heading("4. Real-World Applications", level=1)
            for app in apps:
                doc.add_paragraph(app, style='List Bullet')
        
        # 5. Common Mistakes
        mistakes = result_data.get('common_mistakes', [])
        if mistakes:
            doc.add_heading("5. Common Mistakes & Confusions", level=1)
            for m in mistakes:
                doc.add_paragraph(m, style='List Bullet')
        
        # 6. Smart Keywords
        smart_kw = result_data.get('smart_keywords', [])
        if smart_kw:
            doc.add_page_break()
            doc.add_heading("6. Smart Keywords + Definitions", level=1)
            for kw in smart_kw:
                doc.add_heading(kw['term'], level=2)
                doc.add_paragraph(f"Meaning: {kw['meaning']}")
                doc.add_paragraph(f"Memory Trick: {kw['trick']}")
        
        # 7. Active Recall
        recall = result_data.get('active_recall', {})
        if recall:
            doc.add_page_break()
            doc.add_heading("7. Active Recall Mode", level=1)
            if recall.get('qa_cards'):
                doc.add_heading("Q&A Flashcards", level=2)
                for i, card in enumerate(recall['qa_cards'], 1):
                    doc.add_paragraph(f"Q{i}: {card['question']}")
                    doc.add_paragraph(f"A: {card['answer']}")
            if recall.get('mcqs'):
                doc.add_heading("MCQs", level=2)
                for i, mcq in enumerate(recall['mcqs'], 1):
                    doc.add_paragraph(f"Q{i}: {mcq['question']}")
                    for j, opt in enumerate(mcq['options']):
                        doc.add_paragraph(f"  {chr(65+j)}) {opt}")
                    doc.add_paragraph(f"  Answer: {mcq['answer']}")
            if recall.get('true_false'):
                doc.add_heading("True or False", level=2)
                for i, tf in enumerate(recall['true_false'], 1):
                    ans = "True" if tf['answer'] else "False"
                    doc.add_paragraph(f"{i}. {tf['statement']} -- {ans}")
            if recall.get('fill_blanks'):
                doc.add_heading("Fill in the Blanks", level=2)
                for i, fb in enumerate(recall['fill_blanks'], 1):
                    doc.add_paragraph(f"{i}. {fb['question']}")
                    doc.add_paragraph(f"   Answer: {fb['answer']}")
        
        doc.save("exam_study_notes.docx")
        print("Word exported successfully")
        return "exam_study_notes.docx"
    except Exception as e:
        raise RuntimeError(f"Word export failed: {str(e)}")


def export_to_json(result_data):
    """Export all data to JSON"""
    try:
        with open("lecture_summary.json", "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2, default=str)
        print("JSON exported successfully")
    except Exception as e:
        raise RuntimeError(f"JSON export failed: {str(e)}")


def _limit_text(value, max_chars):
    if not isinstance(value, str):
        return value
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "..."


def _limit_list(value, count):
    if isinstance(value, list):
        return value[:count]
    return value


def apply_summary_length_profile(result_data, summary_length="Medium"):
    level = (summary_length or "Medium").strip().lower()
    if level == "detailed":
        result_data["summary_length"] = "Detailed"
        return result_data

    if level == "brief":
        list_limits = {
            "topics": 5,
            "applications": 4,
            "common_mistakes": 4,
            "smart_keywords": 8,
            "core_concepts": {"definitions": 3, "formulas": 2, "mechanisms": 3, "processes": 2},
            "exam_insights": {"faq_points": 4, "short_answers": 4, "long_answers": 2, "tricky_areas": 3},
            "active_recall": {"qa_cards": 6, "mcqs": 4, "true_false": 4, "fill_blanks": 4},
        }
        text_limits = {
            "cleaned_text": 4000,
            "concept_snapshot": {"what": 320, "why": 220, "where": 220},
        }
        label = "Brief"
    else:
        list_limits = {
            "topics": 8,
            "applications": 6,
            "common_mistakes": 6,
            "smart_keywords": 12,
            "core_concepts": {"definitions": 6, "formulas": 4, "mechanisms": 6, "processes": 4},
            "exam_insights": {"faq_points": 6, "short_answers": 6, "long_answers": 3, "tricky_areas": 5},
            "active_recall": {"qa_cards": 10, "mcqs": 6, "true_false": 6, "fill_blanks": 6},
        }
        text_limits = {
            "cleaned_text": 9000,
            "concept_snapshot": {"what": 520, "why": 360, "where": 360},
        }
        label = "Medium"

    result_data["topics"] = _limit_list(result_data.get("topics", []), list_limits["topics"])
    result_data["applications"] = _limit_list(result_data.get("applications", []), list_limits["applications"])
    result_data["common_mistakes"] = _limit_list(result_data.get("common_mistakes", []), list_limits["common_mistakes"])
    result_data["smart_keywords"] = _limit_list(result_data.get("smart_keywords", []), list_limits["smart_keywords"])

    core = result_data.get("core_concepts", {})
    for key, count in list_limits["core_concepts"].items():
        core[key] = _limit_list(core.get(key, []), count)
    result_data["core_concepts"] = core

    exam = result_data.get("exam_insights", {})
    for key, count in list_limits["exam_insights"].items():
        exam[key] = _limit_list(exam.get(key, []), count)
    result_data["exam_insights"] = exam

    recall = result_data.get("active_recall", {})
    for key, count in list_limits["active_recall"].items():
        recall[key] = _limit_list(recall.get(key, []), count)
    result_data["active_recall"] = recall

    snapshot = result_data.get("concept_snapshot", {})
    snapshot["what"] = _limit_text(snapshot.get("what", ""), text_limits["concept_snapshot"]["what"])
    snapshot["why"] = _limit_text(snapshot.get("why", ""), text_limits["concept_snapshot"]["why"])
    snapshot["where"] = _limit_text(snapshot.get("where", ""), text_limits["concept_snapshot"]["where"])
    result_data["concept_snapshot"] = snapshot

    result_data["cleaned_text"] = _limit_text(result_data.get("cleaned_text", ""), text_limits["cleaned_text"])
    result_data["summary_length"] = label
    return result_data


def process_input(source_type="mic", file_path=None, duration=10, export_format="PDF", pdf_text=None, stop_event=None, summary_length="Medium"):
    try:
        cleanup_files = []
        if source_type == "mic":
            file_path = record_audio(duration=duration, stop_event=stop_event)
            if not file_path:
                if stop_event is not None and stop_event.is_set():
                    return {"error": "Recording stopped by user."}
                return {"error": "Microphone recording failed. Please check microphone permissions/device and try again."}
            transcript = transcribe_audio(file_path)
            cleanup_files.append(file_path)
        elif source_type == "file" and file_path:
            transcript = transcribe_audio(file_path)
        elif source_type == "pdf" and pdf_text:
            transcript = pdf_text
        else:
            return {"error": "Invalid input source."}

        # Clean and organize text
        print("Cleaning and organizing text...")
        cleaned_text = clean_and_organize_text(transcript)
        
        # Extract main topics
        print("Identifying main topics...")
        topics = extract_main_topics(cleaned_text)
        
        # Generate all 8 sections
        print("1/8 Generating Concept Snapshot...")
        concept_snapshot = generate_concept_snapshot(cleaned_text)
        
        print("2/8 Building Core Concepts Breakdown...")
        core_concepts = generate_core_concepts(cleaned_text)
        
        print("3/8 Creating Exam-Focused Insights...")
        exam_insights = generate_exam_insights(cleaned_text)
        
        print("4/8 Finding Real-World Applications...")
        applications = generate_real_world_applications(cleaned_text)
        
        print("5/8 Identifying Common Mistakes...")
        common_mistakes = generate_common_mistakes(cleaned_text)
        
        print("6/8 Building Smart Keywords...")
        smart_keywords = generate_smart_keywords(cleaned_text)
        
        print("7/8 Creating Active Recall Questions...")
        active_recall = generate_active_recall(cleaned_text)
        
        print("8/8 Assessing Difficulty Level...")
        difficulty = assess_difficulty_level(cleaned_text)

        result_data = {
            "concept_snapshot": concept_snapshot,
            "core_concepts": core_concepts,
            "exam_insights": exam_insights,
            "applications": applications,
            "common_mistakes": common_mistakes,
            "smart_keywords": smart_keywords,
            "active_recall": active_recall,
            "difficulty": difficulty,
            "topics": topics,
            "cleaned_text": cleaned_text
        }

        result_data = apply_summary_length_profile(result_data, summary_length)

        output_file = ""
        export_format = export_format.upper()
        
        if export_format == "PDF":
            output_file = export_to_pdf(result_data)
        elif export_format == "WORD":
            output_file = export_to_word(result_data)
        elif export_format == "MARKDOWN":
            output_file = export_to_markdown(result_data)
        elif export_format == "JSON":
            export_to_json(result_data)
            output_file = "lecture_summary.json"
        else:
            return {"error": "Unsupported export format."}

        for f in cleanup_files:
            if os.path.exists(f): os.remove(f)

        result_data["output_file"] = output_file
        return result_data

    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    print("֎ Choose input method:")
    print("1.  Mic")
    print("2.  File")
    choice = input("Enter choice [1/2]: ")

    if choice == "1":
        duration = float(input(" Enter duration (minutes): "))
        result = process_input(source_type="mic", duration=int(duration * 60), export_format="PDF")
    elif choice == "2":
        path = input(" Enter file path: ")
        result = process_input(source_type="file", file_path=path, export_format="PDF")
    else:
        print("➶ Invalid choice.")
        exit()

    if "error" in result:
        print(" Error:", result["error"])
    else:
        print("𒉽 Summary generated! File saved as:", result["output_file"])