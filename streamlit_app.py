# streamlit_app.py
import streamlit as st
import pandas as pd
import math
from io import StringIO, BytesIO

# === CONFIG ===
WASTE_FACTOR = 1.03   # internal only
KERF = 0              # set to e.g. 3 if you want saw allowance per cut

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

# --- normalise helper
def normalise(text):
    if not isinstance(text, str):
        return ""
    s = text.upper()
    s = s.replace(" ", "").replace("-", "").replace("/", "")
    s = s.replace("\u00D8", "⌀").replace("Ø", "⌀")
    return s

STANDARD_LENGTHS = {normalise(k): v for k, v in RAW_STANDARD_LENGTHS.items()}
STOCK_LIST = [normalise(k) for k in RAW_STOCK_LIST]

# --- Streamlit init
st.set_page_config(page_title="Steel Optimiser", layout="wide")
for key in ["std_overrides", "paste_df", "uploaded_df"]:
    if key not in st.session_state:
        st.session_state[key] = None if "df" in key else {}

# =========================================================
# ✅ APPROVED CUT OPTIMISER (First-Fit Decreasing, bar by bar)
# =========================================================
def optimise_cuts(cut_lengths, std_length):
    """
    Human-friendly optimiser:
    - Sort cuts longest → shortest
    - Fill one bar at a time
    - Skip cuts that don't fit
    - Use smaller cuts to consume offcuts
    """

    if std_length is None:
        return len(cut_lengths), [0] * len(cut_lengths), [[c] for c in cut_lengths]

    cuts = sorted(cut_lengths, reverse=True)
    bars = []

    while cuts:
        remaining = std_length
        bar = []

        # Always take the largest remaining cut first
        first = cuts[0]
        if first > remaining:
            raise ValueError(f"Cut {first}mm longer than bar {std_length}mm")

        bar.append(first)
        remaining -= first + KERF
        cuts.pop(0)

        # Fill bar with anything that fits
        i = 0
        while i < len(cuts):
            if cuts[i] <= remaining:
                bar.append(cuts[i])
                remaining -= cuts[i] + KERF
                cuts.pop(i)
            else:
                i += 1

        bars.append(bar)

    offcuts = [std_length - sum(bar) for bar in bars]
    return len(bars), offcuts, bars

# --- BOM paste parser
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
    raise ValueError("Could not parse pasted BOM.")

# === UI ===
st.title("🔩 Steel Optimiser")

multiplier = st.number_input(
    "How many turntables are we procuring for?",
    min_value=1,
    value=1,
    step=1
)

tab1, tab2 = st.tabs(["Paste BOM", "Upload file"])

with tab1:
    paste_text = st.text_area("Paste BOM here", height=220)
    if paste_text.strip():
        df_temp = try_parse_paste(paste_text)
        df_temp = st.data_editor(df_temp, num_rows="dynamic")
        st.session_state.paste_df = df_temp

with tab2:
    uploaded_file = st.file_uploader("Upload CSV/XLSX", type=["csv", "xls", "xlsx"])
    if uploaded_file:
        df_up = pd.read_csv(uploaded_file) if uploaded_file.name.endswith(".csv") else pd.read_excel(uploaded_file)
        df_up = st.data_editor(df_up, num_rows="dynamic")
        st.session_state.uploaded_df = df_up

df_source = (
    st.session_state.paste_df
    if st.session_state.paste_df is not None
    else st.session_state.uploaded_df
)

if df_source is None:
    st.stop()

cols = {c.lower(): c for c in df_source.columns}
df = df_source.rename(columns={
    cols["description"]: "Description",
    cols["length"]: "Length",
    cols["qty"]: "Qty"
})

df["Qty"] = pd.to_numeric(df["Qty"], errors="coerce").fillna(0).astype(int) * multiplier
df["Length"] = pd.to_numeric(df["Length"], errors="coerce")
df["desc_norm"] = df["Description"].apply(normalise)
df["Parent"] = df.get("Parent", "")

# --- Length overrides
st.header("Material length confirmation")
for d in df["desc_norm"].unique():
    name = df.loc[df["desc_norm"] == d, "Description"].iloc[0]
    default = STANDARD_LENGTHS.get(d)
    val = st.text_input(name, value=str(default) if default else "")
    if val.strip():
        st.session_state.std_overrides[d] = int(val)

# --- Process
if st.button("Process BOM"):
    buy_rows = []

    for desc, g in df.groupby("desc_norm"):
        std_len = st.session_state.std_overrides.get(desc, STANDARD_LENGTHS.get(desc))
        cuts_nom = []
        cuts_eff = []

        for _, r in g.iterrows():
            cuts_nom.extend([math.ceil(r["Length"])] * r["Qty"])
            cuts_eff.extend([math.ceil(r["Length"] * WASTE_FACTOR)] * r["Qty"])

        bars, offcuts, patterns_eff = optimise_cuts(cuts_eff, std_len)

        patterns_nom = []
        idx = 0
        for bar in patterns_eff:
            bar_nom = []
            for _ in bar:
                bar_nom.append(cuts_nom[idx])
                idx += 1
            patterns_nom.append(bar_nom)

        buy_rows.append({
            "Description": g["Description"].iloc[0],
            "Standard Bar Length": std_len,
            "Bars Required": bars,
            "Avg Offcut": round(sum(offcuts) / len(offcuts), 1),
            "Cutting Patterns": patterns_nom
        })

    out_df = pd.DataFrame(buy_rows)
    st.dataframe(out_df, use_container_width=True)
    st.success("Optimisation complete.")
