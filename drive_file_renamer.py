import os
import pickle
import json
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# --- ENV SETUP ---
load_dotenv()
SOURCE_FOLDER_ID = os.getenv("SOURCE_FOLDER_ID").replace("'", '').replace('"', '').strip()
OAUTH_CREDENTIALS = os.getenv("GOOGLE_OAUTH_CREDENTIALS", "credentials.json")
CACHE_FILE = 'gpt_filename_cache.json'
RENAME_LOG = 'drive_rename_log.json'

SCOPES = ['https://www.googleapis.com/auth/drive']

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

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        return {}

def save_cache(cache):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

def save_rename_log(log):
    with open(RENAME_LOG, 'w', encoding='utf-8') as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

def get_target_filename(parsed_fields, orig_ext):
    # Compose target filename from 5 parts, preserving extension
    return '_'.join(parsed_fields) + orig_ext

def batch_rename_drive_files(drive_service, folder_id, cache):
    page_token = None
    renamed = 0
    skipped = 0
    # We'll store all rename operations here
    rename_log = []
    # Create quick lookup for cache by both old and new name
    cache_by_old = {k: v for k, v in cache.items() if k not in ['examples', 'rename_log']}
    cache_by_new = {}

    for k, v in cache_by_old.items():
        parsed = v.get('parsed', [""]*5)
        ext = os.path.splitext(k)[1]
        tgt_name = get_target_filename(parsed, ext)
        cache_by_new[tgt_name] = v

    while True:
        resp = drive_service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name)",
            pageToken=page_token
        ).execute()
        for f in resp.get('files', []):
            curr_name = f['name']
            file_id = f['id']
            ext = os.path.splitext(curr_name)[1]
            # Try to find record by current or intended name
            cache_entry = cache_by_old.get(curr_name) or cache_by_new.get(curr_name)
            if cache_entry:
                parsed = cache_entry.get('parsed', [""]*5)
                tgt_name = get_target_filename(parsed, ext)
                if curr_name != tgt_name:
                    print(f"Renaming in Drive: {curr_name} -> {tgt_name}")
                    drive_service.files().update(fileId=file_id, body={"name": tgt_name}).execute()
                    rename_log.append({
                        "file_id": file_id,
                        "old_name": curr_name,
                        "new_name": tgt_name
                    })
                    # Optional: update cache, so it can always be accessed by latest name
                    if curr_name in cache and tgt_name not in cache:
                        cache[tgt_name] = cache.pop(curr_name)
                    renamed += 1
                else:
                    skipped += 1
            else:
                print(f"Skipping (not in cache): {curr_name}")
                skipped += 1
        page_token = resp.get('nextPageToken', None)
        if page_token is None:
            break
    print(f"Renamed {renamed} files. Skipped {skipped} files.")
    # Save rename log in a separate file and in cache for easy reference
    cache["rename_log"] = rename_log
    save_cache(cache)
    save_rename_log(rename_log)

if __name__ == "__main__":
    print("Authorizing with Google OAuth 2.0...")
    creds = get_google_creds()
    drive_service = build('drive', 'v3', credentials=creds)
    print(f"Renaming files in Google Drive folder {SOURCE_FOLDER_ID}...")
    cache = load_cache()
    batch_rename_drive_files(drive_service, SOURCE_FOLDER_ID, cache)
    print("Drive renaming complete. All operations logged in drive_rename_log.json.")
