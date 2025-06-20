import os
import json
import pandas as pd
import openai
import streamlit as st

# --- Load secrets directly from Streamlit ---
OPENAI_API_KEY = st.secrets["OPENAI_KEY"]
CACHE_FILE = 'gpt_filename_cache.json'
EXAMPLES_KEY = 'examples'

FIELDNAMES = [
    "Item Code",
    "Brand",
    "Product + Variant",
    "Dimensions",
    "No. of Colours",
]

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {EXAMPLES_KEY: []}

def save_cache(cache):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

def load_cache_df():
    cache = load_cache()
    rows = []
    for fname, entry in cache.items():
        if fname == EXAMPLES_KEY:
            continue
        parsed = entry.get('parsed', [""]*5)
        notes = entry.get('notes', "")
        view_url = entry.get('view_url', "")
        rows.append(parsed + [fname, notes, view_url])
    df = pd.DataFrame(rows, columns=FIELDNAMES + [
        "Filename", "Notes", "View URL"
    ])
    return cache, df

def simple_query_df(df, user_query):
    q = user_query.lower()
    import re
    if "dettol" in q:
        df = df[df["Brand"].str.contains("dettol", case=False, na=False)]
    if "germol" in q:
        df = df[df["Brand"].str.contains("germol", case=False, na=False)]
    if "godrej" in q:
        df = df[df["Brand"].str.contains("godrej", case=False, na=False)]
    if "cool" in q:
        df = df[df["Product + Variant"].str.contains("cool", case=False, na=False)]
    match = re.search(r"(\d+)[xX](\d+)", q)
    if match:
        w, h = match.group(1), match.group(2)
        df = df[df["Dimensions"].str.contains(f"{w}X{h}", case=False, na=False)]
    if "col" in q:
        match = re.search(r"(\d+)col", q)
        if match:
            col_num = int(match.group(1))
            df = df[df["No. of Colours"].astype(str).str.extract(r"(\d+)").astype(float)[0] == col_num]
    if "above" in q and "col" in q:
        match = re.search(r"above\s+(\d+)", q)
        if match:
            min_col = int(match.group(1))
            df = df[df["No. of Colours"].astype(str).str.extract(r"(\d+)").astype(float)[0] > min_col]
    return df

def gpt_query(user_query, cache):
    EXAMPLES = [
        {
            "filename": "3103159_Dettol_Soap_Cool_Menthol_96X135MM_9COL.pdf",
            "parsed": [
                "3103159", "Dettol", "Soap_Cool_Menthol", "96X135MM", "9COL"
            ],
            "notes": "Standard Dettol soap spec. Product+Variant combined: Soap_Cool_Menthol."
        },
        {
            "filename": "ITM-GER-004_Germol_Soap_Lemon_174X95MM_5COL.png",
            "parsed": [
                "ITM-GER-004", "Germol", "Soap_Lemon", "174X95MM", "5COL"
            ],
            "notes": "Non-numeric code example. Product+Variant is Soap_Lemon."
        },
        {
            "filename": "20042586_Godrej_Soap_LimeAloeVera_126X169MM_8COL.pdf",
            "parsed": [
                "20042586", "Godrej", "Soap_LimeAloeVera", "126X169MM", "8COL"
            ],
            "notes": "Godrej LimeAloeVera, 8 colors. Product+Variant combined: Soap_LimeAloeVera."
        },
    ]
    examples = cache.get(EXAMPLES_KEY, [])[:2] + EXAMPLES
    context_examples = "\n".join([
        f"{ex['filename']} => {ex['parsed']} (Note: {ex['notes']})"
        for ex in examples
    ])
    system_msg = (
        "You are a filename parser for packaging spec files. "
        "Every filename is always in the format: "
        "ItemCode_Brand_Product+Variant_Dimensions_NoOfColours.ext — always 5 parts, underscores as delimiters. "
        "Product+Variant may have internal underscores. Do NOT split Product+Variant further. "
        "Here are examples:\n"
        f"{context_examples}\n"
        "Given a new filename, split it into the 5 parts as shown. "
        "Return as JSON: {\"parsed\": [...], \"notes\": \"...\"}"
    )
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_query}
        ],
        max_tokens=256,
        temperature=0
    )
    return resp.choices[0].message.content

def main():
    st.set_page_config(page_title="SpecBot", page_icon="📦", layout="wide")
    st.title("📦 Smart SpecBot")
    st.write(
        "All filenames must be in the format:\n"
        "`ItemCode_Brand_Product+Variant_Dimensions_NoOfColours.ext`\n\n"
        "e.g. `3103159_Dettol_Soap_Cool_Menthol_96X135MM_9COL.pdf`\n\n"
        "- Product + Variant can contain underscores (do not split further)\n"
        "- Only the first four underscores are delimiters."
    )

    cache, df = load_cache_df()
    user_query = st.text_input(
        "Ask a question (e.g., Show me all Dettol files above 8COL, or explain 3103159_Dettol_Soap_Cool_Menthol_96X135MM_9COL.pdf):", "")

    if user_query:
        filtered_df = simple_query_df(df, user_query)
        if not filtered_df.empty:
            st.write("### Results:")
            st.dataframe(filtered_df, use_container_width=True)
        else:
            with st.spinner("Thinking..."):
                try:
                    result = gpt_query(user_query, cache)
                except Exception as e:
                    st.error(f"GPT Query Error: {e}")
                    return
            st.markdown("**GPT says:**")
            st.markdown(result)

    st.markdown("---")
    st.subheader("📝 Edit or Correct Parsed Data")
    cache = load_cache()
    filenames = [fname for fname in cache if fname != EXAMPLES_KEY]

    for fname in filenames:
        entry = cache[fname]
        fields = entry.get('parsed', [""]*5)
        notes = entry.get('notes', "")
        view_url = entry.get('view_url', "")
        with st.expander(f"Filename: {fname}"):
            cols = st.columns(5)
            f0 = cols[0].text_input(f"Item Code", value=fields[0], key=f"{fname}_0")
            f1 = cols[1].text_input(f"Brand", value=fields[1], key=f"{fname}_1")
            f2 = cols[2].text_input(f"Product + Variant", value=fields[2], key=f"{fname}_2")
            f3 = cols[3].text_input(f"Dimensions", value=fields[3], key=f"{fname}_3")
            f4 = cols[4].text_input(f"No. of Colours", value=fields[4], key=f"{fname}_4")
            new_notes = st.text_area("Notes", value=notes, key=f"{fname}_notes")
            if st.button(f"Save changes for {fname}", key=f"save_{fname}"):
                cache[fname]['parsed'] = [f0, f1, f2, f3, f4]
                cache[fname]['notes'] = new_notes
                save_cache(cache)
                st.success(f"Updated entry for {fname}")
            if view_url:
                if fname.lower().endswith('.pdf'):
                    st.markdown(f"[View PDF in Drive]({view_url})", unsafe_allow_html=True)
                    # Embed preview if possible
                    preview_url = view_url.replace('/view?usp=drivesdk', '/preview')
                    st.components.v1.iframe(preview_url, height=500)
                elif fname.lower().endswith(('.png', '.jpg', '.jpeg')):
                    st.image(view_url)
                else:
                    st.markdown(f"[Open file in Drive]({view_url})", unsafe_allow_html=True)
            else:
                st.info("No view link available for this file.")

    with st.expander("Show all files (full table)"):
        st.dataframe(df, use_container_width=True)

if __name__ == "__main__":
    main()
