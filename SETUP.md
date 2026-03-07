# HSA Receipt Tracker — Setup Guide

## Prerequisites
- Python 3.10+
- A Google account (the one that owns the HSA Drive folder)

---

## 1. Create a Google Cloud Project & Enable APIs

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown at the top → **New Project**
3. Name it something like "HSA Tracker" → **Create**
4. Make sure the new project is selected in the dropdown
5. Go to **APIs & Services → Library** (or search "API Library" in the top search bar)
6. Search for and **enable** each of these:
   - **Google Drive API**
   - **Google Sheets API**

## 2. Create OAuth Credentials

1. Go to **APIs & Services → Credentials**
2. Click **+ CREATE CREDENTIALS → OAuth client ID**
3. If prompted to configure the consent screen:
   - Choose **External** (it's fine — only you will use it)
   - Fill in just the required fields: App name ("HSA Tracker"), user support email (your email), developer contact (your email)
   - Click **Save and Continue** through Scopes and Test Users (no changes needed)
   - On the **Test Users** screen, click **+ Add Users** and add your own Gmail address
   - Click **Save and Continue**, then **Back to Dashboard**
4. Now go back to **Credentials → + CREATE CREDENTIALS → OAuth client ID**
5. Application type: **Desktop app**
6. Name: "HSA Tracker" (or anything)
7. Click **Create**
8. Click **Download JSON** on the confirmation dialog
9. **Rename** the downloaded file to `credentials.json` and put it in the `hsa-tracker/` folder (next to `app.py`)

## 3. Install Python Dependencies

```bash
cd hsa-tracker
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Configure Environment

```bash
cp .env.example .env
```

The `.env` file is pre-filled with your Google Sheet and Drive folder IDs. If you want Claude-powered auto-extraction of receipt fields, add your Anthropic API key to the `ANTHROPIC_API_KEY` line.

## 5. Run the App

```bash
python app.py
```

The first time you run it:
1. Your browser will open a Google sign-in page
2. Sign in with the Google account that owns the HSA Drive folder
3. You'll see a "Google hasn't verified this app" warning — click **Advanced → Go to HSA Tracker (unsafe)**
   - This is expected for personal OAuth apps; it's your own app accessing your own data
4. Grant the requested permissions (Drive and Sheets access)
5. The browser will redirect to a success page and the app will save a `token.json` file

After the first run, the app uses the saved token and won't ask again (until it expires, which is rare).

## 6. Use It

Open http://localhost:5050 in your browser. Drop a PDF receipt:

1. The app extracts text from the PDF
2. If you set up the Anthropic API key, it auto-fills vendor, date, amount, etc.
3. Review the fields, adjust if needed
4. Click **File Receipt**
5. The PDF gets uploaded to the right `YYYY-MM` folder in your Drive
6. A new row gets appended to your Google Sheet

---

## Troubleshooting

**"credentials.json not found"**
→ You need to download the OAuth credentials from Google Cloud Console (step 2.8 above) and place them in the `hsa-tracker/` directory.

**"Access blocked: HSA Tracker has not completed the Google verification process"**
→ Make sure you added your email as a test user in the OAuth consent screen configuration (step 2.3).

**"Token has been expired or revoked"**
→ Delete `token.json` and restart the app. It will re-authenticate.

**"HttpError 403: The caller does not have permission"**
→ Make sure you're signed in with the Google account that owns the HSA Drive folder and Sheet, and that you enabled both the Drive API and Sheets API.

**Claude auto-extraction not working**
→ Check that `ANTHROPIC_API_KEY` is set in your `.env` file. The app works fine without it — you'll just fill in the fields manually.
