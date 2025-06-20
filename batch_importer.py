import os
import json
import pandas as pd
import re
import pickle
from dotenv import load_dotenv

import openai
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ----- ENV and CONFIG -----
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SOURCE_FOLDER_ID = os.getenv("SOURCE_FOLDER_ID").replace("'", '').replace('"', '').strip()
OAUTH_CREDENTIALS = os.getenv("GOOGLE_OAUTH_CREDENTIALS", "credentials.json")
CACHE_FILE = 'gpt_filename_cache.json'
EXAMPLES_KEY = 'examples'

# ---- OPENAI 1.x CLIENT ----
client = openai.OpenAI(api_key=OPENAI_API_KEY)

SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets'
]

def get_google_creds():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CREDENTIALS, SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds

def build_google_services():
    creds = get_google_creds()
    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)
    return drive_service, sheets_service

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        return {EXAMPLES_KEY: []}

def save_cache(cache):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

def list_drive_files(drive_service, folder_id):
    files = []
    page_token = None
    while True:
        resp = drive_service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name)",
            pageToken=page_token
        ).execute()
        files.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken', None)
        if page_token is None:
            break
    return files

def build_gpt_prompt(filename, cache):
    examples = cache.get(EXAMPLES_KEY, [])[:5]
    examples_txt = "\n".join([
        f"{ex['filename']} -> {ex['parsed']} (Note: {ex['notes']})"
        for ex in examples
    ]) if examples else "No prior examples available."
    prompt = (
        "You are a file naming expert for print/packaging specs. "
        "Given a filename, parse these 5 fields, treating underscores only as delimiters: "
        "[Item Code, Brand, Product+Variant, Dimensions, No. of Colours].\n"
        "Product+Variant may contain underscores inside, do not split further. "
        "Hyphens and numbers can appear anywhere. Always explain edge cases or corrections in notes.\n"
        "Here are some parsed filenames with notes:\n"
        f"{examples_txt}\n"
        f"Now parse: {filename}\n"
        "Return as JSON: "
        "{\"parsed\": [..fields..], \"notes\": \"...\"}"
    )
    return prompt

def gpt_parse_filename(filename, cache):
    prompt = build_gpt_prompt(filename, cache)
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
            temperature=0
        )
        content = response.choices[0].message.content
        data = json.loads(content)
        parsed, notes = data['parsed'], data.get('notes', '')
        return parsed, notes
    except Exception as e:
        print("GPT parsing error:", e)
        return ["", "", "", "", ""], f"GPT error: {e}"

def parse_filename(filename):
    name, _ = os.path.splitext(filename)
    parts = name.split('_', 4)
    if len(parts) == 5:
        return parts, "Standard 5-part parse (Product+Variant combined)."
    else:
        return None, None

def batch_parse_and_update_cache(files, cache):
    drive_base = "https://drive.google.com/file/d/"
    updated = False
    for file in files:
        filename = file['name']
        file_id = file['id']
        view_url = f"{drive_base}{file_id}/view?usp=drivesdk"
        if filename in cache:
            cache[filename]['view_url'] = view_url  # Always update view link
            continue  # Skip already cached for parse
        parts, notes = parse_filename(filename)
        if parts:
            cache[filename] = {
                "parsed": parts,
                "notes": notes,
                "source": "Rule",
                "corrected_by": None,
                "view_url": view_url
            }
        else:
            parsed, gpt_notes = gpt_parse_filename(filename, cache)
            cache[filename] = {
                "parsed": parsed,
                "notes": gpt_notes,
                "source": "GPT",
                "corrected_by": None,
                "view_url": view_url
            }
        # Add to few-shot examples if high quality
        if len(cache[filename]['parsed']) == 5 and all(cache[filename]['parsed']):
            cache.setdefault(EXAMPLES_KEY, [])
            cache[EXAMPLES_KEY].append({
                "filename": filename,
                "parsed": cache[filename]["parsed"],
                "notes": cache[filename]["notes"],
                "source": cache[filename]["source"],
                "corrected_by": None,
                "view_url": view_url
            })
            if len(cache[EXAMPLES_KEY]) > 20:
                cache[EXAMPLES_KEY] = cache[EXAMPLES_KEY][-20:]
        updated = True
    return updated

def write_to_gsheet(cache, sheets_service, gsheet_id, tab_name="Parsed_Files"):
    rows = []
    for fname, entry in cache.items():
        if fname == EXAMPLES_KEY:
            continue
        parsed = entry.get('parsed', [""]*5)
        notes = entry.get('notes', "")
        view_url = entry.get('view_url', "")
        rows.append(parsed + [fname, notes, view_url])
    df = pd.DataFrame(rows, columns=[
        "Item Code", "Brand", "Product + Variant", "Dimensions", "No. of Colours",
        "Filename", "Notes", "View URL"
    ])
    values = [df.columns.tolist()] + df.values.tolist()
    body = {'values': values}
    try:
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=gsheet_id,
            body={
                "requests": [{
                    "addSheet": {
                        "properties": {"title": tab_name}
                    }
                }]
            }
        ).execute()
    except Exception:
        pass
    sheets_service.spreadsheets().values().update(
        spreadsheetId=gsheet_id,
        range=f"{tab_name}!A1",
        valueInputOption="RAW",
        body=body
    ).execute()
    print("Google Sheet updated.")

if __name__ == "__main__":
    print("Authorizing with Google OAuth 2.0...")
    drive_service, sheets_service = build_google_services()
    print("Scanning Google Drive folder for files...")
    files = list_drive_files(drive_service, SOURCE_FOLDER_ID)
    print(f"Found {len(files)} files. Loading cache...")
    cache = load_cache()
    cache_updated = batch_parse_and_update_cache(files, cache)
    if cache_updated:
        print(f"Cache updated. {len(cache) - len(cache.get(EXAMPLES_KEY, []))} files now cached.")
        save_cache(cache)
    else:
        print("No updates made to cache.")

    # Always sync cache to Google Sheet!
    print("Syncing to Google Sheet...")
    write_to_gsheet(cache, sheets_service, GOOGLE_SHEET_ID)
    print("Done.")
