import streamlit as st
import pandas as pd
import os
import io
import matplotlib.pyplot as plt

from zipfile import ZipFile
from tempfile import NamedTemporaryFile

# Constants for machine types
CARDING = 1
DF = 2
FLYER = 3

# Title
st.title("CAN Log Decoder and Visualizer")

# File uploads
log_file = st.file_uploader("Upload CAN log text file", type=["txt", "log"])
dbc_file = st.file_uploader("Upload DBC.ods file", type=["ods"])
flyer_plan_file = st.file_uploader("(Optional) Upload Flyer Communication Plan (xlsx)", type=["xlsx"])

# Machine selection
machine_type = st.selectbox("Select Machine Type", ("CARDING", "DF", "FLYER"))
machine_map = {"CARDING": CARDING, "DF": DF, "FLYER": FLYER}
machine = machine_map[machine_type]

if log_file and dbc_file:
    # Load the DBC file
    functionIDs = pd.read_excel(dbc_file, engine="odf", index_col=0, sheet_name="FunctionID")
    CardingAddressIDs = pd.read_excel(dbc_file, engine="odf", index_col=0, sheet_name="Carding_IDs")
    DFAddressIDs = pd.read_excel(dbc_file, engine="odf", index_col=0, sheet_name="DF_IDs")
    FlyerAddressIDs = pd.read_excel(dbc_file, engine="odf", index_col=0, sheet_name="FF_IDs")
    Operations = pd.read_excel(dbc_file, engine="odf", index_col=0, sheet_name="Operation")
    Errors = pd.read_excel(dbc_file, engine="odf", index_col=2, sheet_name="Error")

    # Read log lines
    lines = log_file.read().decode("utf-8").splitlines()

    allDicts = []
    for line in lines:
        splits = line.split(" ")
        if 'rcv' in splits:
            try:
                linedict = {}
                date = splits[0][1:]
                time = splits[1][:-1]
                extID = splits[3]
                hexData = splits[4]

                source = extID[-2:]
                dst = extID[-4:-2]
                fID = extID[-6:-4]

                linedict.update({
                    "date": date,
                    "time": time,
                    "extID": extID,
                    "hexData": hexData,
                    "msgType": functionIDs.loc[str(fID), "msgType"]
                })

                machineIDs = {
                    CARDING: CardingAddressIDs,
                    DF: DFAddressIDs,
                    FLYER: FlyerAddressIDs
                }[machine]

                linedict["source"] = machineIDs.loc[str(source), "name"]
                linedict["dst"] = machineIDs.loc[str(dst), "name"]

                if linedict["msgType"] == "Operation":
                    linedict["OperationCommand"] = Operations.loc[str(hexData), "msgType"]
                elif linedict["msgType"] == "Error":
                    linedict["ErrorCommand"] = Errors.loc[int(str(hexData)), "msgType"]

                if machine == FLYER and len(hexData) >= 40:
                    try:
                        data_bytes = bytes.fromhex(hexData)
                        linedict.update({
                            "targetPosition": ((data_bytes[0] << 8) | data_bytes[1]) / 100.0,
                            "presentPosition": ((data_bytes[2] << 8) | data_bytes[3]) / 100.0,
                            "presentRPM": (data_bytes[4] << 8) | data_bytes[5],
                            "appliedDuty": (data_bytes[6] << 8) | data_bytes[7],
                            "FETtemp": data_bytes[8],
                            "MOTtemp": data_bytes[9],
                            "busCurrentADC": (data_bytes[10] << 8) | data_bytes[11],
                            "busVoltageADC": (data_bytes[12] << 8) | data_bytes[13],
                            "liftDirection": data_bytes[14],
                            "GBPresentPosition": ((data_bytes[15] << 8) | data_bytes[16]) / 100.0,
                            "encPresentPosition": ((data_bytes[17] << 8) | data_bytes[18]) / 100.0,
                            "usingPosition": data_bytes[19]
                        })

                        # Determine lift side based on source or destination
                        src = linedict.get("source", "").lower()
                        dst = linedict.get("dst", "").lower()
                        if "right" in src or "right" in dst:
                            linedict["LiftSide"] = "Right Lift"
                        elif "left" in src or "left" in dst:
                            linedict["LiftSide"] = "Left Lift"
                        else:
                            linedict["LiftSide"] = "Unknown Lift"

                    except Exception as decode_err:
                        st.warning(f"Flyer decoding error: {decode_err}")

                allDicts.append(linedict)
            except Exception as e:
                st.warning(f"Line parsing error: {e}")

    df = pd.DataFrame(allDicts)
    st.success("Log file processed.")
    st.dataframe(df.head())

    # CSV Download
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("Download CSV", csv, "decoded_log.csv", "text/csv")

    # Separate Lift Sheets Export
    if "LiftSide" in df.columns:
        right_df = df[df["LiftSide"] == "Right Lift"]
        left_df = df[df["LiftSide"] == "Left Lift"]

        with NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            with pd.ExcelWriter(tmp.name, engine="xlsxwriter") as writer:
                right_df.to_excel(writer, sheet_name="Right Lift", index=False)
                left_df.to_excel(writer, sheet_name="Left Lift", index=False)

            with open(tmp.name, "rb") as f:
                st.download_button(
                    "Download Right/Left Lift Sheets",
                    data=f,
                    file_name="lift_sheets.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

    # Enhanced Plotting Section
    st.subheader("Plot Data Comparison")

    if "LiftSide" in df.columns:
        lift_filter = st.selectbox("Filter by Lift Side", ["All", "Right Lift", "Left Lift"])
        if lift_filter != "All":
            filtered_df = df[df["LiftSide"] == lift_filter]
        else:
            filtered_df = df
    else:
        filtered_df = df

    numeric_columns = filtered_df.select_dtypes(include="number").columns.tolist()
    compare_cols = st.multiselect("Select numeric columns to plot", numeric_columns)

    if compare_cols:
        fig, ax = plt.subplots()
        for col in compare_cols:
            filtered_df[col].plot(ax=ax, label=col)
        ax.set_title(f"Comparison Plot ({lift_filter})")
        ax.legend()
        st.pyplot(fig)

    # Flyer-specific plan display
    if machine == FLYER and flyer_plan_file:
        flyer_df = pd.read_excel(flyer_plan_file)
        st.subheader("Flyer Communication Plan Data")
        st.dataframe(flyer_df.head())
