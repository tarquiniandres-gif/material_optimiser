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

# --- Build list of unique normalised descriptions
df_work["desc_norm"] = df_work["Description"].apply(normalise)
unique_desc = df_work["desc_norm"].unique().tolist()

st.header("Material length confirmation")
st.markdown("Confirm or type a custom stock length for each normalised Description. Leave blank to use known standard or the global default. Type `CUT` to mark as cut-to-length.")

# --- Editable length overrides
for desc in unique_desc:
    display_example = df_work.loc[df_work["desc_norm"] == desc, "Description"].iloc[0]
    std_known = STANDARD_LENGTHS.get(desc)
    override_val = st.session_state.std_overrides.get(desc, None)
    default_str = ""
    if override_val == "CUT":
        default_str = "CUT"
    elif override_val is not None:
        default_str = str(override_val)
    elif std_known is not None:
        default_str = str(std_known)
    col_a, col_b = st.columns([4,2])
    with col_a:
        st.write(f"**{display_example}**  — key: `{desc}`")
    with col_b:
        inp = st.text_input(f"Length for {desc}", value=default_str, key=f"len_{desc}")
        val = inp.strip().upper()
        if val == "":
            st.session_state.std_overrides.pop(desc, None)
        elif val == "CUT":
            st.session_state.std_overrides[desc] = "CUT"
        else:
            try:
                num = int(float(val))
                st.session_state.std_overrides[desc] = num
            except Exception:
                st.warning(f"Ignoring invalid length for {desc}: '{inp}' (use number or CUT)")

st.markdown("---")
st.write("Global default stock length (used when neither a standard nor an override exists):", default_stock_length, "mm")

# --- PROCESS BUTTON
if st.button("Process BOM"):
    st.info("Processing — building BUY and CHECK lists...")
    buy_rows = []
    check_rows = []
    warnings = []

    # Determine grouping
    if procure_mode.startswith("By Parent"):
        group_keys = ["Parent", "desc_norm"]
        grouped = df_work.groupby(group_keys, as_index=False)
    else:
        grouped = df_work.groupby("desc_norm", as_index=False)

    for group_key, group_df in grouped:
        if procure_mode.startswith("By Parent"):
            parent, desc_norm = group_key
            readable = group_df["Description"].iloc[0]
            parent_label = parent if parent not in (None, "") else "(No Parent)"
            title_label = f"{parent_label} — {readable}"
        else:
            desc_norm = group_key
            readable = group_df["Description"].iloc[0]
            parent_label = None
            title_label = f"{readable}"

        st.subheader(title_label)

        group_df["Length"] = pd.to_numeric(group_df["Length"], errors="coerce")
        group_df["Qty"] = pd.to_numeric(group_df["Qty"], errors="coerce").fillna(0).astype(int)

        # Compose cuts
        cuts = []
        for _, r in group_df.iterrows():
            if pd.isna(r["Length"]) or r["Qty"] <= 0:
                continue
            length_mm = math.ceil(float(r["Length"]) * WASTE_FACTOR)
            cuts.extend([int(length_mm)] * int(r["Qty"]))

        if not cuts:
            st.write("No valid cuts found in this group.")
            continue

        # Determine standard length
        std_len = None
        if desc_norm in st.session_state.std_overrides:
            val = st.session_state.std_overrides[desc_norm]
            if val == "CUT":
                std_len = None
            else:
                std_len = int(val)
        else:
            std_len = STANDARD_LENGTHS.get(desc_norm, None)

        used_len = std_len if std_len is not None else default_stock_length
        used_from = "STANDARD" if std_len is not None else "GLOBAL DEFAULT"
        explicit_cut = (desc_norm in st.session_state.std_overrides and st.session_state.std_overrides[desc_norm] == "CUT")

        if explicit_cut:
            bars_needed = len(cuts)
            offcuts = [0]*bars_needed
            patterns = [[c] for c in cuts]
            buy_rows.append({
                "Parent": parent_label if parent_label else "(Bulk)",
                "Description": readable,
                "Standard Bar Length (mm)": "CUT-TO-LENGTH",
                "Total Cuts": len(cuts),
                "Bars Required": bars_needed,
                "Avg Offcut (mm)": 0,
                "Cutting Patterns": str(patterns)
            })
            st.write("Cut-to-length selected — no bar packing performed.")
            st.write(f"Cuts: {cuts}")
            continue

        bars_needed, offcuts, patterns = optimise_cuts(cuts, used_len)
        avg_off = round(sum(offcuts)/len(offcuts),1) if offcuts else 0

        if desc_norm in STOCK_LIST:
            total_length = sum(cuts)
            approx_bars_equiv = round(total_length / (used_len or 1), 2)
            check_rows.append({
                "Parent": parent_label if parent_label else "(Bulk)",
                "Description": readable,
                "Total Length (mm)": total_length,
                "Approx. Bars Equivalent": approx_bars_equiv,
                "Used Stock Length (mm)": used_len
            })
            st.write("Stock material (CHECK):")
            st.write(f"Total length: {total_length} mm  —  Approx bars: {approx_bars_equiv}")
        else:
            buy_rows.append({
                "Parent": parent_label if parent_label else "(Bulk)",
                "Description": readable,
                "Standard Bar Length (mm)": used_len,
                "Total Cuts": len(cuts),
                "Bars Required": bars_needed,
                "Avg Offcut (mm)": avg_off,
                "Cutting Patterns": str(patterns)
            })
            st.write(f"Used stock length for optimisation: {used_len} mm ({used_from})")
            st.write(f"Bars required: **{bars_needed}** — Avg offcut: {avg_off} mm")
            for i, p in enumerate(patterns, start=1):
                st.write(f"Bar {i}: {p} → used {sum(p)} mm | waste {used_len - sum(p)} mm")

    # Build dataframes for export
    buy_df = pd.DataFrame(buy_rows)
    check_df = pd.DataFrame(check_rows)

    st.markdown("---")
    st.subheader("📦 BUY LIST")
    st.dataframe(buy_df if not buy_df.empty else pd.DataFrame(), use_container_width=True)

    st.subheader("📘 CHECK (Stock Materials)")
    st.dataframe(check_df if not check_df.empty else pd.DataFrame(), use_container_width=True)

    missing = [d for d in unique_desc if d not in st.session_state.std_overrides and STANDARD_LENGTHS.get(d) is None]
    if missing:
        with st.expander("⚠️ Descriptions without known standard length (consider adding overrides)"):
            for m in missing:
                st.warning(f"{m} — example: {df_work.loc[df_work['desc_norm']==m,'Description'].iloc[0]}")

    # Export to Excel
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        buy_df.to_excel(writer, sheet_name="BUY", index=False)
        check_df.to_excel(writer, sheet_name="CHECK", index=False)
    out.seek(0)
    st.download_button("⬇️ Download Excel output", data=out, file_name="Steel_Optimiser_Output.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.success("Processing complete.")
