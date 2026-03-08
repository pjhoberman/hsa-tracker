"""
HSA Receipt Tracker
Drop a PDF receipt → extracts data → files it in Google Drive → logs it in your Sheet.
"""

import os
import json
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import pdfplumber

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

load_dotenv()

app = Flask(__name__)
APP_DIR = Path(__file__).parent
app.config["UPLOAD_FOLDER"] = APP_DIR / "uploads"
app.config["UPLOAD_FOLDER"].mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Configuration — override via .env or environment variables
# ---------------------------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]
SPREADSHEET_ID = os.getenv(
    "SPREADSHEET_ID", "15kITxdnKjCm3bbM5bzcsXJzbqMGh4boACibQXjX_F6w"
)
DRIVE_PARENT_FOLDER_ID = os.getenv(
    "DRIVE_FOLDER_ID", "1mvXAYtXj9C6pjJkIH17WpRTSNY9uwbf3"
)
SHEET_NAME = os.getenv("SHEET_NAME", "Sheet1")

# Optional — set OPENAI_API_KEY to enable auto-extraction
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


# ---------------------------------------------------------------------------
# Google Auth
# ---------------------------------------------------------------------------
def get_google_creds():
    """Get or refresh Google OAuth2 credentials (desktop app flow)."""
    creds = None
    token_path = APP_DIR / "token.json"
    creds_path = APP_DIR / "credentials.json"

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    "credentials.json not found. See SETUP.md for instructions."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=8081)
        token_path.write_text(creds.to_json())

    return creds


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------
def extract_pdf_text(filepath: Path) -> str:
    """Extract all text from a PDF."""
    text = ""
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text.strip()


# ---------------------------------------------------------------------------
# OpenAI-based field extraction (optional)
# ---------------------------------------------------------------------------
def extract_fields_with_openai(text: str, filename: str) -> dict | None:
    """Use OpenAI to pull structured fields from receipt text. Returns None on failure."""
    if not OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract receipt/invoice information from this text. "
                        "Return ONLY valid JSON (no markdown fences) with these fields:\n"
                        '- "vendor": company or provider name\n'
                        '- "service_date": date of service, format M/D/YY (e.g. "3/15/25")\n'
                        '- "amount": dollar amount as a number string, no $ sign\n'
                        '- "date_paid": payment date if shown (same format), or ""\n'
                        '- "paid_via": payment method if mentioned, or ""\n'
                        '- "notes": very brief description of what was purchased/service, or ""\n\n'
                        f'Filename: "{filename}"\n\n'
                        f"Receipt text:\n{text[:4000]}"
                    ),
                }
            ],
        )
        raw = response.choices[0].message.content.strip()
        # Handle potential markdown fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)
    except Exception as e:
        print(f"[OpenAI extraction] {e}")
        return None


# ---------------------------------------------------------------------------
# Google Drive helpers
# ---------------------------------------------------------------------------
def get_or_create_month_folder(drive_service, date_str: str):
    """Find or create the YYYY-MM folder under the HSA parent folder."""
    try:
        parts = date_str.strip().split("/")
        month = int(parts[0])
        if len(parts) >= 3 and parts[2]:
            year = int(parts[2])
            year = year + 2000 if year < 100 else year
        else:
            year = datetime.now().year
        folder_name = f"{year}-{month:02d}"
    except (ValueError, IndexError):
        now = datetime.now()
        folder_name = f"{now.year}-{now.month:02d}"

    # Check if folder already exists
    query = (
        f"name = '{folder_name}' and "
        f"'{DRIVE_PARENT_FOLDER_ID}' in parents and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false"
    )
    results = (
        drive_service.files()
        .list(q=query, spaces="drive", fields="files(id, name)")
        .execute()
    )
    folders = results.get("files", [])
    if folders:
        return folders[0]["id"], folder_name

    # Create folder
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [DRIVE_PARENT_FOLDER_ID],
    }
    folder = drive_service.files().create(body=metadata, fields="id").execute()
    return folder["id"], folder_name


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    has_ai = bool(OPENAI_API_KEY)
    return render_template("index.html", has_ai=has_ai)


@app.route("/upload", methods=["POST"])
def upload():
    """Accept PDF, extract text, optionally auto-extract fields."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported right now"}), 400

    filepath = app.config["UPLOAD_FOLDER"] / file.filename
    file.save(filepath)

    try:
        text = extract_pdf_text(filepath)
    except Exception as e:
        filepath.unlink(missing_ok=True)
        return jsonify({"error": f"PDF extraction failed: {e}"}), 500

    fields = extract_fields_with_openai(text, file.filename) or {
        "vendor": "",
        "service_date": "",
        "amount": "",
        "date_paid": "",
        "paid_via": "",
        "notes": "",
    }

    return jsonify(
        {
            "filename": file.filename,
            "text": text[:6000],
            "fields": fields,
        }
    )


@app.route("/submit", methods=["POST"])
def submit():
    """Upload PDF to Drive and append a row to the Sheet."""
    data = request.json
    filename = data.get("filename", "")
    filepath = app.config["UPLOAD_FOLDER"] / filename

    if not filepath.exists():
        return jsonify({"error": "File not found — please re-upload."}), 400

    try:
        creds = get_google_creds()
        drive_svc = build("drive", "v3", credentials=creds)
        sheets_svc = build("sheets", "v4", credentials=creds)

        # 1. Upload to the correct YYYY-MM folder
        folder_id, folder_name = get_or_create_month_folder(
            drive_svc, data.get("service_date", "")
        )
        file_meta = {"name": filename, "parents": [folder_id]}
        media = MediaFileUpload(str(filepath), mimetype="application/pdf")
        uploaded = (
            drive_svc.files()
            .create(body=file_meta, media_body=media, fields="id,webViewLink")
            .execute()
        )

        # 2. Append row to the Google Sheet
        row = [
            data.get("vendor", ""),
            data.get("service_date", ""),
            data.get("amount", ""),
            data.get("date_paid", ""),
            data.get("paid_via", ""),
            "",  # Invoice — usually blank
            f'=HYPERLINK("{uploaded.get("webViewLink", "")}", "{filename}")',  # Receipt
            data.get("notes", ""),
        ]
        sheets_svc.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A:H",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        # 3. Clean up local temp file
        filepath.unlink(missing_ok=True)

        return jsonify(
            {
                "success": True,
                "folder": folder_name,
                "drive_link": uploaded.get("webViewLink", ""),
                "message": f"Filed in {folder_name} and added to spreadsheet.",
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    print("\n  HSA Receipt Tracker → http://localhost:5050\n")
    app.run(debug=debug, port=5050)
