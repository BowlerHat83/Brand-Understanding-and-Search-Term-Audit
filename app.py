import streamlit as st
import os
import sys

st.title("📁 Streamlit Environment Directory Diagnostic")

st.subheader("Current Working Directory Path:")
st.code(os.getcwd())

st.subheader("Files Visible inside this Container Workspace:")
try:
    files = os.listdir(".")
    st.write(files)
except Exception as e:
    st.error(f"Failed to read directory: {e}")

st.subheader("Python System Search Paths (sys.path):")
st.write(sys.path)
