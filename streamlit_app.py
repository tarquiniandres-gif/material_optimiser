# streamlit_app.py
import streamlit as st
import pandas as pd
import math
from io import StringIO, BytesIO

# === CONFIG ===
WASTE_FACTOR = 1.03

RAW_STANDARD_LENGTHS = {
    "50X50X3SHS": 8000,
    "100X50X3RHS": 7000,
    "125PFC": 12000,
    "75X50X3RHS": 8000,
    "150PFC": 12000,
    "150X50X5RHS": 8000,
    "40X40X2.5SHS": 8000,
    "40X40X3SHS": 8000,
    "150X50X3RHS": 8000,
    "65X35X2.5RHS": 8000,
    "75X75X6EA": 9000,
    "50X50X5EA": 9000,
    "50X50X3EA": 9000,
    "25X25X3EA": 9000,
    "40X40X5EA": 7500,
    "25X25X2SHS": 6500,
    "25X25X2.5SHS": 6500,
    "⌀6BAR": 6000,
    "⌀12BAR": 6000,
    "40X5FL(MS)": 6000,
    "40X3FL(MS)": 6000,
    "200PFC": None
}

RAW_STOCK_LIST = [
    "100X50X3RHS",
    "75X50X3RHS",
    "40X40X2.5RHS",
    "65X35X2.5RHS",
    "40X40X5EA",
    "⌀6BAR",
    "⌀12BAR"
]

# --- normalise helper (for Description -> key)
def normalise(text):
    if not isinstance(text, str):
        return ""
    s = text.upper()
    s = s.replace(" ", "")
    s = s.replace("-", "")
    s = s.replace("/", "")
    s = s.replace("\u00D8", "⌀")  # Ø variants
    s = s.replace("Ø", "⌀")
    return s

# Prepare standard dict keyed by normalised keys
STANDARD_LENGTHS = {normalise(k): v for k, v in RAW_STANDARD_LENGTHS.items()}
STOCK_LIST = [normalise(k) for k in RAW_STOCK_LIST]

# --- Streamlit session-state safe initialisation
st.set_page_config(page_title="Steel Optimiser", layout="wide")
if "std_overrides" not in st.session_state:
    st.session_state.std_overrides = {}
if "custom_materials" not in st.session_state:
    st.session_state.custom_materials = {}
if "paste_df" not in st.session_state:
    st.session_state.paste_df = None
if "uploaded_df" not in st.session_state:
    st.session_state.uploaded_df = None

# --- helper algorithms
def best_fit_decreasing(cuts, bar_length):
    cuts = sorted(cuts, reverse=True)
    bars = []
    for cut in cuts:
        placed = False
        for bar in bars:
            if sum(bar) + cut <= bar_length:
                bar.append(cut)
                placed = True
                break
        if not placed:
            bars.append([cut])
    return bars

def optimise_cuts(cut_lengths, std_length):
    if std_length is None:
        total_length = sum(cut_lengths)
        return 1, [0], [cut_lengths]
    bars = best_fit_decreasing(cuts=cut_lengths, bar_length=std_length)
    offcuts = [std_length - sum(bar) for bar in bars]
    return len(bars), offcuts, bars

# --- parsing pasted text robustly
def try_parse_paste(paste_text):
    txt = paste_text.strip()
    if not txt:
        raise ValueError("Empty paste.")
    for sep in ["\t", ",", ";"]:
        try:
            df = pd.read_csv(StringIO(txt), sep=sep)
            cols = {c.strip().lower() for c in df.columns}
            if {"description", "length", "qty"} <= cols:
                return df
        except Exception:
            continue
    lines = txt.splitlines()
    header = lines[0]
    sep = "\t" if "\t" in header else ","
    df = pd.DataFrame([l.split(sep) for l in lines[1:]], columns=[h.strip() for h in header.split(sep)])
    cols = {c.strip().lower() for c in df.columns}
    if {"description", "length", "qty"} <= cols:
        return df
    raise ValueError("Could not parse pasted BOM. Ensure headers include Description, Length, Qty.")

# --- UI Header
st.title("🔩 Steel Optimiser — Paste or Upload BOM")
st.markdown("Paste a BOM copied from Excel (headers included) or upload a CSV/XLSX. Required columns: **Description, Length, Qty**. Optional: **Parent, Material**.")

with st.expander("Sample minimal BOM (CSV/TSV)"):
    st.code(
        "Description,Material,Length,Qty,Parent\n"
        "50 x 50 x 3 SHS,Tubeline,1200,2,Parent A\n"
        "100 x 50 x 3 RHS,Tubeline,1500,3,Parent A\n"
        "50 x 50 x 3 SHS,Tubeline,1200,3,Parent B\n"
        "100 x 50 x 3 RHS,Tubeline,1500,2,Parent B"
    )

# --- Sidebar: stock length, overrides, multiplier, and procurement mode
st.sidebar.subheader("Stock length / Overrides")
default_stock_length = st.sidebar.number_input("Global default stock length (mm)", min_value=100, max_value=20000, value=6000, step=100)

st.sidebar.markdown("**Session: add or override a material**")
add_name = st.sidebar.text_input("Material Description (free text)", value="")
add_len = st.sidebar.text_input("Stock length (mm) or type CUT", value="")
if st.sidebar.button("Add / Override material (session)"):
    key = normalise(add_name)
    if not key:
        st.sidebar.error("Enter a material description")
    else:
        v = add_len.strip().upper()
        if v == "CUT":
            st.session_state.std_overrides[key] = "CUT"
            st.sidebar.success(f"{key} set to CUT-TO-LENGTH")
        else:
            try:
                num = int(float(v))
                st.session_state.std_overrides[key] = num
                st.sidebar.success(f"{key} -> {num} mm (override)")
            except Exception:
                st.sidebar.error("Invalid length. Use a number (mm) or CUT")

# --- Sidebar: procurement options & multiplier
st.sidebar.subheader("Procurement options")
multiplier = st.sidebar.number_input(
    "How many turntables are we procuring for?",
    min_value=1,
    value=1,
    step=1,
    help="All quantities in the BOM will be multiplied by this number"
)
procure_mode = st.sidebar.radio(
    "Procure by",
    ["Bulk (group by Description)", "By Parent (bundle per Parent)"],
    index=0
)

# --- Input tabs (Paste / Upload)
tab1, tab2 = st.tabs(["Paste BOM (recommended)", "Upload file"])
with tab1:
    paste_text = st.text_area("Paste BOM here (copy from Excel with headers).", height=220)
    if paste_text.strip():
        try:
            df_temp = try_parse_paste(paste_text)
            df_temp.columns = [c.strip() for c in df_temp.columns]
            st.info("Review / edit pasted table below before processing.")
            df_temp = st.data_editor(df_temp, num_rows="dynamic")
            st.session_state.paste_df = df_temp
        except Exception as e:
            st.error(str(e))
with tab2:
    uploaded_file = st.file_uploader("Upload BOM (CSV or Excel)", type=["csv", "xlsx", "xls"])
    if uploaded_file:
        try:
            if uploaded_file.name.lower().endswith(".csv"):
                df_up = pd.read_csv(uploaded_file)
            else:
                df_up = pd.read_excel(uploaded_file)
            df_up.columns = [c.strip() for c in df_up.columns]
            df_up = st.data_editor(df_up, num_rows="dynamic")
            st.session_state.uploaded_df = df_up
        except Exception as e:
            st.error(f"Error reading file: {e}")

# --- Choose source
df_source = st.session_state.paste_df if st.session_state.paste_df is not None else st.session_state.uploaded_df
if df_source is None:
    st.info("Paste or upload a BOM to continue.")
    st.stop()

# --- Ensure relevant columns exist
cols_map = {c.lower(): c for c in df_source.columns}
required = {"description", "length", "qty"}
if not required <= set(cols_map.keys()):
    st.error("BOM must include Description, Length, and Qty columns (case-insensitive).")
    st.stop()

# --- Rename to consistent column names
df_work = df_source.rename(
    columns={cols_map["description"]:"Description", cols_map["length"]:"Length", cols_map["qty"]:"Qty"}
)
df_work["Parent"] = df_source[cols_map["parent"]] if "parent" in cols_map else ""
df_work["Material"] = df_source[cols_map["material"]] if "material" in cols_map else ""

# --- Apply multiplier to Qty
try:
    df_work["Qty"] = pd.to_numeric(df_work["Qty"], errors="coerce").fillna(0).astype(int) * int(multiplier)
except Exception:
    st.error("Qty column must be numeric.")
    st.stop()

# --- Continue with existing code: normalisation, overrides, editable lengths, processing...
# (All your previous logic for building BUY/CHECK lists remains the same.)
# ...
