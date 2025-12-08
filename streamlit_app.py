import streamlit as st
import pandas as pd
from math import floor

st.set_page_config(page_title="Steel Optimiser", layout="wide")

# Raw standard lengths
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

# -----------------------------------------
# SESSION STATE INITIALIZATION
# -----------------------------------------

if "material_lengths" not in st.session_state:
    st.session_state.material_lengths = RAW_STANDARD_LENGTHS.copy()

if "paste_df" not in st.session_state:
    st.session_state.paste_df = None

if "uploaded_df" not in st.session_state:
    st.session_state.uploaded_df = None


# -----------------------------------------
# HELPERS
# -----------------------------------------

def parse_pasted_table(text):
    """
    Converts pasted Excel BOM text into a DataFrame (tab or comma separated).
    """
    lines = text.strip().split("\n")
    if len(lines) < 2:
        raise ValueError("Not enough lines detected.")

    sep = "\t" if "\t" in lines[0] else ","
    columns = [c.strip() for c in lines[0].split(sep)]
    rows = [l.split(sep) for l in lines[1:]]
    df = pd.DataFrame(rows, columns=columns)

    return df


def optimise_material(material, df):

    std_length = st.session_state.material_lengths.get(material)

    if std_length is None or std_length == 0:
        return {
            "material": material,
            "std_length": None,
            "qty_required": None,
            "cuts": [],
            "message": "⚠️ No standard length defined. Please set it above."
        }

    cuts = df["Length"].astype(float).tolist()
    cuts_sorted = sorted(cuts, reverse=True)

    bars = []
    current_bar = []

    remaining = std_length

    for cut in cuts_sorted:
        if cut <= remaining:
            current_bar.append(cut)
            remaining -= cut
        else:
            bars.append(current_bar)
            current_bar = [cut]
            remaining = std_length - cut

    if current_bar:
        bars.append(current_bar)

    return {
        "material": material,
        "std_length": std_length,
        "qty_required": len(bars),
        "cuts": bars,
        "message": "OK"
    }


# -----------------------------------------
# UI START
# -----------------------------------------

st.title("🔩 Steel Material Optimiser")

st.markdown("Paste your BOM or upload it below.")

tab1, tab2 = st.tabs(["📋 Paste BOM", "📁 Upload File"])

# ------------------------
# TAB 1: PASTE BOM
# ------------------------
with tab1:
    pasted = st.text_area("Paste BOM from Excel (with headers)", height=220)

    if pasted.strip():
        try:
            df = parse_pasted_table(pasted)
            df = st.data_editor(df, num_rows="dynamic")
            st.session_state.paste_df = df
        except Exception as e:
            st.error(f"Error parsing BOM: {e}")

# ------------------------
# TAB 2: UPLOAD FILE
# ------------------------
with tab2:
    file = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx"])

    if file:
        try:
            if file.name.endswith(".csv"):
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file)

            df = st.data_editor(df, num_rows="dynamic")
            st.session_state.uploaded_df = df
        except Exception as e:
            st.error(f"Error loading file: {e}")


# -----------------------------------------
# CHOOSE DF SOURCE
# -----------------------------------------
df_source = st.session_state.uploaded_df or st.session_state.paste_df

if df_source is None:
    st.info("Please paste or upload a BOM to continue.")
    st.stop()

st.header("🔢 Procurement Options")

qty_turntables = st.number_input("How many turntables are we procuring for?", min_value=1, value=1)

bundle_option = st.radio(
    "Procurement mode:",
    ["Bulk (all cuts combined)", "By Parent (each parent separately)"]
)

# Multiply quantities
df_source["Qty"] = df_source["Qty"].astype(float) * qty_turntables

# -----------------------------------------
# MATERIAL LENGTH EDITOR
# -----------------------------------------

st.header("📏 Material Length Overrides")

st.markdown("Adjust any bar length. Values are saved automatically.")

for mat in sorted(st.session_state.material_lengths.keys()):
    current = st.session_state.material_lengths[mat]

    new_val = st.number_input(
        f"{mat} length (mm)",
        min_value=0,
        step=100,
        value=current if current else 0,
        key=f"matlen_{mat}"
    )

    st.session_state.material_lengths[mat] = new_val if new_val > 0 else None


st.divider()

# -----------------------------------------
# PROCESS BUTTON
# -----------------------------------------

if st.button("🚀 Process BOM"):
    st.header("📦 Optimisation Results")

    if bundle_option == "Bulk (all cuts combined)":
    grouped = df_source.groupby("Material")
else:
    grouped = df_source.groupby(["Parent", "Material"])

for group, subdf in grouped:

    # -------- Determine material key --------
    if isinstance(group, tuple):
        parent, material_key = group
        st.subheader(f"Parent: {parent} | Material: {material_key}")
    else:
        material_key = group
        st.subheader(f"Material: {material_key}")

    # Validate numeric columns
    try:
        subdf2 = subdf.copy()
        subdf2["Length"] = subdf2["Length"].astype(float)
        subdf2["Qty"] = subdf2["Qty"].astype(float)
    except:
        st.error("Length & Qty must be numeric.")
        continue

    # Expand quantities into individual cut entries
    expanded = subdf2.loc[subdf2.index.repeat(subdf2["Qty"])]

    # -------- Call optimiser with actual material key --------
    result = optimise_material(material_key, expanded)

    # Show message if no length
    if result["std_length"] is None:
        st.warning(result["message"])
        continue

    st.write(f"Standard length: **{result['std_length']} mm**")
    st.write(f"Bars required: **{result['qty_required']}**")

    # Show cut pattern
    for i, cuts in enumerate(result["cuts"], start=1):
        st.write(
            f"Bar {i}: {cuts} → Used {sum(cuts)} mm | Waste {result['std_length'] - sum(cuts)} mm"
        )

    st.divider()
