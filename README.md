# Study Hub

Study Hub is a Streamlit app that turns lecture files and PDFs into structured study material: summaries, outlines, key points, flashcards, analytics, and exportable notes.

## What this project does

- User authentication with signup/login (local SQLite database)
- Session-based login persistence (DB session token + local temp token file)
- Input support:
    - Audio/video file upload (`wav`, `mp3`, `m4a`, `mp4`, `avi`, `mov`)
    - PDF upload with text extraction + OCR fallback
- AI processing pipeline:
    - Transcription using Whisper
    - Summarization and study-asset generation using Hugging Face Transformers (`google/flan-t5-base`)
- Summary length control: `Brief`, `Medium`, `Detailed`
- Output sections include:
    - Concept snapshot
    - Core concepts (definitions, formulas, mechanisms, processes)
    - Exam insights
    - Applications and common mistakes
    - Active-recall flashcards
    - Difficulty scoring
- Export formats from UI: `PDF`, `Markdown`, `Word`
- Study history, analytics, and personal notes per user

## Tech stack

- Frontend/UI: Streamlit + custom CSS
- Transcription: OpenAI Whisper
- Summarization: Transformers pipeline
- PDF parsing: `pdfplumber`, `PyPDF2`
- OCR fallback: `pytesseract`, `Pillow`
- Export: `fpdf`, `python-docx`
- Database: SQLite (`notes_app.db`)

## Project structure

- `main.py` - main Streamlit app UI and flow
- `auth.py` - login/signup screens and auth helpers
- `database.py` - SQLite schema + data access for users/sessions/history/notes
- `lecture_processor.py` - transcription, summarization, PDF/OCR, export logic
- `style.css` - additional styling
- `requirements.txt` - Python dependencies
- `screenshots/` - UI screenshots

## Setup

### 1) Clone and enter project

```bash
git clone https://github.com/ReZo-s4m/StudyHub.git
cd StudyHub
```

### 2) Create and activate virtual environment (recommended)

```bash
python -m venv .venv
```

Windows PowerShell:

```bash
.venv\Scripts\Activate.ps1
```

### 3) Install dependencies

```bash
pip install -r requirements.txt
```

### 4) Initialize local database (first run)

```bash
python -c "import database; database.init_db()"
```

### 5) Run the app

```bash
streamlit run main.py
```

## Optional system dependency (OCR)

OCR for image-based PDFs requires Tesseract installed on your machine.

- Install Tesseract (Windows):
    - https://github.com/UB-Mannheim/tesseract/wiki
- Ensure Tesseract is available in PATH (or configured properly) for `pytesseract`.

If Tesseract is not installed, standard PDF text extraction still works for text-based PDFs.

## Data and storage notes

- Auth, study history, and personal notes are stored locally in `notes_app.db`.
- Uploaded files are written to temp local files during processing, then removed.
- Generated exports are saved locally (`exam_study_notes.pdf/.md/.docx`).
- `.gitignore` is configured to avoid committing local DB and generated artifacts.

## Current limitations

- No cloud backend by default (data is local to the machine)
- No multi-device shared accounts unless you integrate a hosted backend

## License

This project includes an MIT license file in the repository.
