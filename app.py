"""Minimal single-page Streamlit app to check Floci status."""

import streamlit as st

from start_floci import FLOCI_URL, ping_floci

st.set_page_config(page_title="Floci Status", layout="centered")
st.title("Floci Status")
st.write(f"Endpoint: `{FLOCI_URL}`")

is_up, message = ping_floci()

if is_up:
    st.success(message)
else:
    st.error(message)
    st.caption("Run `python start_floci.py` to start Floci.")

if st.button("Ping Floci"):
    st.rerun()
