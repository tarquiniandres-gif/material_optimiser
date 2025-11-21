import streamlit as st
import pandas as pd
import math
from io import BytesIO, StringIO

# === CONFIGURATION ===
WASTE_FACTOR = 1.03

# --- Standard lengths ---
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

# --- Normalisation ---
STOCK_LIST = [k.upper() for k in RAW_STOCK_LIST]
STANDARD_LENGTHS = {k.upper(): v for k, v in RAW_STANDARD_LENGTHS.items()}

def normalise(text):
    if not isinstance(text, str):
        return ""
    text = text.upper().replace(" ", "").replace("-", "").replace("/", "")
    text = text.replace("X", "X").replace("Ø", "⌀").replace("Ø", "⌀")
    return text

# --- Core Functions ---
def best_fit_decreasing(cuts, bar_length):
    cuts = sorted(cuts, reverse=True)
    bars = []
    for cut in cuts:
        placed = False
        for bar in bars:
            remaining = bar_length - sum(bar)
            if remaining >= cut:
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
    bars = best_fit_decreasing(cut_lengths, std_length)
    offcuts = [std_length - sum(bar) for bar in bars]
    return len(bars), offcuts, bars

def process_group(df_group):
    buy_rows, check_rows = [], []
    df = df_group.copy()
    df["desc_clean"] = df["description"].apply(normalise)
    grouped = df.groupby("desc_clean", as_index=False)
    for desc_norm, group in grouped:
        if not desc_norm:
            continue
        desc_display = group["description"].iloc[0].strip()
        cuts = []
        for _, row in group.iterrows():
            try:
                length = float(row["length"])
                qty = int(row["qty"])
                cuts.extend([math.ceil(length * WASTE_FACTOR)] * qty)
            except:
                continue
        std_length = STANDARD_LENGTHS.get(desc_norm)
        if std_length is None and "200PFC" not in desc_norm:
            buy_rows.append({
                "Description": desc_display,
                "Standard Bar Length (mm)": "UNKNOWN",
                "Total Cuts": len(cuts),
                "Bars Required": "UNKNOWN",
                "Avg Offcut (mm)": "UNKNOWN",
                "Cutting Patterns": "UNKNOWN",
                "_warning": f"No standard length found for {desc_display}"
            })
            continue
        if "200PFC" in desc_norm:
            std_length = None
        if desc_norm in STOCK_LIST:
            total_length = sum(cuts)
            bars_equiv = total_length / (std_length or 1)
            check_rows.append({
                "Description": desc_display,
                "Total Length (mm)": total_length,
                "Approx. Bars Equivalent": round(bars_equiv,2)
            })
        else:
            bars_needed, offcuts, patterns = optimise_cuts(cuts, std_length)
            buy_rows.append({
                "Description": desc_display,
                "Standard Bar Length (mm)": std_length or "CUT-TO-LENGTH",
                "Total Cuts": len(cuts),
                "Bars Required": bars_needed,
                "Avg Offcut (mm)": round(sum(offcuts)/len(offcuts),1) if offcuts else 0,
                "Cutting Patterns": str(patterns)
            })
    return buy_rows, check_rows

# --- Parsing Helpers ---
def try_parse_paste(paste_text):
    s = StringIO(paste_text.strip())
    for sep in [",","\t",";"]:
        try:
            df = pd.read_csv(s, sep=sep)
            if {"description","length","qty"} <= set(c.lower() for c in df.columns):
                return df
        except:
            continue
    df = pd.read_csv(StringIO(paste_text))
    if {"description","length","qty"} <= set(c.lower() for c in df.columns):
        return df
    raise ValueError("Could not parse pasted BOM. Ensure headers include Description, Length, Qty.")

def load_file_uploaded(uploaded):
    if uploaded.name.lower().endswith((".xls",".xlsx")):
        return pd.read_excel(uploaded)
    else:
        return pd.read_csv(uploaded)

# === Streamlit UI ===
st.set_page_config(page_title="Steel Optimizer", layout="wide")
st.title("🔩 Steel Optimizer — Paste or Upload BOM")

st.markdown(
    """
Paste your BOM (CSV or tab-separated) or upload Excel/CSV.
Required columns: **Description, Length, Qty**.
Optional column: **Parent**.
"""
)

with st.expander("Sample BOM CSV"):
    st.code(
        "Description,Length,Qty,Parent\n"
        "50x50x3SHS,1200,2,Parent A\n"
        "100x50x3RHS,1500,3,Parent A\n"
        "50x50x3SHS,1200,3,Parent B\n"
        "100x50x3RHS,1500,2,Parent B\n"
    )

tab1, tab2 = st.tabs(["Paste BOM", "Upload file"])
paste_df = None
uploaded_df = None

with tab1:
    st.subheader("Paste BOM (or edit table)")
    paste_text = st.text_area("Paste BOM from Excel (with headers)", height=220)

    if paste_text.strip():
        try:
            lines = paste_text.strip().split("\n")
            # detect separator: tab or comma
            sep = "\t" if "\t" in lines[0] else ","
            # convert to DataFrame
            df_temp = pd.DataFrame([l.split(sep) for l in lines[1:]], columns=lines[0].split(sep))
            # strip spaces from column names
            df_temp.columns = [c.strip() for c in df_temp.columns]
            # editable table
            st.write("✅ Review / edit pasted BOM below")
            paste_df = st.data_editor(df_temp, num_rows="dynamic")
        except Exception as e:
            st.error(f"Error parsing pasted BOM: {e}")


with tab2:
    uploaded_file = st.file_uploader("Upload BOM file", type=["xlsx","xls","csv"])
    if uploaded_file:
        try:
            uploaded_df = load_file_uploaded(uploaded_file)
            st.success(f"Loaded {uploaded_file.name}")
            st.dataframe(uploaded_df.head(), use_container_width=True)
        except Exception as e:
            st.error(f"Error reading uploaded file: {e}")

col1,col2,col3 = st.columns([1,1,1])
with col1:
    procure_mode = st.radio("Procure by", ["Bulk (group by Description)","By Parent (bundle per Parent)"], index=0)
with col2:
    multiplier = st.number_input("Number of turntables to procure for", min_value=1,value=1,step=1)
with col3:
    process_btn = st.button("Process BOM")

if process_btn:
    if paste_df is None and uploaded_df is None:
        st.error("No BOM provided.")
    else:
        df = paste_df if paste_df is not None else uploaded_df
        df.columns = [c.strip() for c in df.columns]
        col_map = {c.lower():c for c in df.columns}
        required = ["description","length","qty"]
        if not set(required) <= set(col_map.keys()):
            st.error("BOM must include Description, Length, Qty columns.")
        else:
            df_proc = df.rename(columns={col_map["description"]:"description",
                                         col_map["length"]:"length",
                                         col_map["qty"]:"qty"})
            if "parent" in col_map:
                df_proc = df_proc.rename(columns={col_map["parent"]:"parent"})
            else:
                df_proc["parent"] = ""
            try:
                df_proc["qty"] = df_proc["qty"].astype(float).astype(int)*int(multiplier)
            except:
                st.error("Could not interpret Qty column as numeric integers.")
                st.stop()

            st.info("Processing BOM...")
            buy_rows_all = []
            check_rows_all = []
            warnings = []

            if procure_mode.startswith("By Parent"):
                parents = df_proc["parent"].fillna("").unique()
                for parent in parents:
                    sub = df_proc[df_proc["parent"].fillna("")==parent].copy()
                    if sub.empty: continue
                    buy_rows, check_rows = process_group(sub)
                    for r in buy_rows:
                        r["Parent"] = parent if parent!="" else "(No Parent)"
                        if "_warning" in r:
                            warnings.append(r["_warning"])
                            r.pop("_warning",None)
                    for r in check_rows:
                        r["Parent"] = parent if parent!="" else "(No Parent)"
                    buy_rows_all.extend(buy_rows)
                    check_rows_all.extend(check_rows)
            else:
                buy_rows, check_rows = process_group(df_proc)
                for r in buy_rows:
                    r["Parent"] = "(Bulk)"
                    if "_warning" in r:
                        warnings.append(r["_warning"])
                        r.pop("_warning",None)
                for r in check_rows:
                    r["Parent"] = "(Bulk)"
                buy_rows_all = buy_rows
                check_rows_all = check_rows

            buy_df = pd.DataFrame(buy_rows_all)
            check_df = pd.DataFrame(check_rows_all)

            if not buy_df.empty:
                cols = ["Parent","Description","Standard Bar Length (mm)","Total Cuts","Bars Required","Avg Offcut (mm)","Cutting Patterns"]
                buy_df = buy_df[[c for c in cols if c in buy_df.columns]]
            if not check_df.empty:
                cols_check = ["Parent","Description","Total Length (mm)","Approx. Bars Equivalent"]
                check_df = check_df[[c for c in cols_check if c in check_df.columns]]

            st.subheader("📦 BUY LIST")
            if buy_df.empty:
                st.write("No BUY items found.")
            else:
                st.dataframe(buy_df,use_container_width=True)
            st.subheader("📘 CHECK (Stock Materials)")
            if check_df.empty:
                st.write("No CHECK items found.")
            else:
                st.dataframe(check_df,use_container_width=True)

            if warnings:
                with st.expander("⚠️ Warnings"):
                    for w in warnings:
                        st.warning(w)

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                if not buy_df.empty:
                    buy_df.to_excel(writer, sheet_name="BUY", index=False)
                else:
                    pd.DataFrame().to_excel(writer, sheet_name="BUY", index=False)
                if not check_df.empty:
                    check_df.to_excel(writer, sheet_name="CHECK", index=False)
                else:
                    pd.DataFrame().to_excel(writer, sheet_name="CHECK", index=False)
            output.seek(0)
            st.download_button(
                label="⬇️ Download Excel Output",
                data=output,
                file_name="Steel_Optimizer_Output.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            st.success("Processing complete.")
