python -m streamlit run app.py

Project Overview
This is an intelligent, learning, and fully editable spec/artwork management system for your packaging jobs, built with Python, OpenAI GPT, Google Drive, Google Sheets, and Streamlit.

Renames files in Drive to a strict 5-field convention.

Parses, logs, and audits all file specs with human and AI review.

Lets you review, correct, and preview all artworks from a browser UI.

Google Sheets sync for audit, share, and backup.

Setup (First time)
Place your .env in the project root with these variables (already done in your project):

OPENAI_KEY=sk-...
GOOGLE_SHEET_ID=...
SOURCE_FOLDER_ID=...
Place your credentials.json (Google OAuth2) in the project root.

Install dependencies:

nginx
Copy
Edit
pip install -r requirements.txt
Usage: Run Functions In This Order
1. Rename all files to the correct 5-part structure
bash
Copy
Edit
python drive_file_renamer.py
What it does:
Finds any file in your Drive source folder that isn’t like
ItemCode_Brand_Product+Variant_Dimensions_NoOfColours.ext
(i.e., 4 underscores, 5 fields) and auto-renames it.

Why:
Ensures all later steps, AI parsing, and data linking are predictable and robust.

2. Parse, log, and sync specs to cache and Google Sheet
bash
Copy
Edit
python batch_importer.py
What it does:

Scans all files in the Drive folder.

Parses each filename into 5 fields.

For edge cases or ambiguous files, uses GPT for parsing.

Stores parse results, notes, and Drive view URLs in gpt_filename_cache.json.

Syncs all data to your configured Google Sheet (creating tab if missing).

Why:

This is your database step. Cache is used for search/UI. Sheet is for backup, audit, and sharing.



What it does:

Loads all data from gpt_filename_cache.json.

Lets you search, filter, or use GPT Q&A on all jobs.

Lets you edit and correct all parsed fields and notes in-line (browser).

Lets you preview PDFs/images inline (embedded Google Drive previews).

Lets you click through to the artwork file in Drive.

Why:

Easy, safe review. All edits are instantly saved to your cache for future steps.

4. (Optional) Resync or export
If you want to update Google Sheet after editing in the UI, rerun batch_importer.py.

If you add/rename files in Drive, rerun the renamer and batch importer.
