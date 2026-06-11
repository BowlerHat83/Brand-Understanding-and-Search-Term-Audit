import streamlit as st

st.set_page_config(
    layout="wide",
    page_title="AI PPC Search Terms Auditor"
)

# -----------------------------
# SAFE SESSION STATE INIT
# -----------------------------
def init_state():
    defaults = {
        "stage": 1,
        "blueprint": None,
        "audit_results": None,
        "root_negatives": None,
        "brand": None
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

st.title("🛡️ AI PPC Search Terms Auditor")


# -----------------------------
# LAZY IMPORTS (CRITICAL FIX)
# -----------------------------
@st.cache_resource
def load_stage1():
    from core.stage1_brand import (
        generate_brand_profile,
        list_cached_blueprints,
        load_cached_blueprint
    )
    return generate_brand_profile, list_cached_blueprints, load_cached_blueprint


@st.cache_resource
def load_stage2():
    from core.stage2_audit import run_stage2_audit
    return run_stage2_audit


@st.cache_resource
def load_stage3():
    from core.stage3_export import export_to_excel
    return export_to_excel


# =========================================================
# STAGE 1 — BLUEPRINT
# =========================================================
def stage1():
    generate_brand_profile, list_cached_blueprints, load_cached_blueprint = load_stage1()

    st.header("🧠 Stage 1 — Brand Blueprint")

    cached = []
    try:
        cached = list_cached_blueprints()
    except Exception:
        cached = []

    selection = st.selectbox(
        "Select Existing Blueprint",
        ["-- Create New --"] + cached
    )

    # -----------------------------
    # LOAD EXISTING
    # -----------------------------
    if selection != "-- Create New --":
        blueprint = load_cached_blueprint(selection)

        if blueprint:
            st.session_state.blueprint = blueprint
            st.success("Blueprint loaded")

            if st.button("Continue → Stage 2"):
                st.session_state.stage = 2
                st.rerun()

    # -----------------------------
    # CREATE NEW
    # -----------------------------
    else:
        brand = st.text_input("Brand Name")
        offering = st.text_input("Core Offering")
        landing = st.text_input("Landing Page")

        if st.button("Generate Blueprint"):

            if not brand or not offering or not landing:
                st.error("Please fill all fields")
                return

            with st.spinner("Generating blueprint..."):
                blueprint = generate_brand_profile(
                    brand,
                    offering,
                    landing
                )

            st.session_state.blueprint = blueprint
            st.session_state.brand = brand

            st.success("Blueprint created")

            st.session_state.stage = 2
            st.rerun()


# =========================================================
# STAGE 2 — AUDIT
# =========================================================
def stage2():
    run_stage2_audit = load_stage2()

    st.header("🔍 Stage 2 — Audit Engine")

    if st.button("← Back"):
        st.session_state.stage = 1
        st.rerun()

    file = st.file_uploader("Upload Google Ads CSV", type=["csv"])

    if file:
        import pandas as pd

        df = pd.read_csv(file, encoding="utf-8", on_bad_lines="skip")
        terms = df.iloc[:, 0].dropna().astype(str).tolist()

        st.write(f"Loaded {len(terms)} search terms")

        if st.button("Run Audit"):

            if not st.session_state.blueprint:
                st.error("No blueprint found. Go back to Stage 1.")
                return

            progress = st.progress(0)
            status = st.empty()

            def progress_hook(i, total):
                progress.progress(i / total)
                status.write(f"Processing batch {i}/{total}")

            with st.spinner("Running classification..."):
                results = run_stage2_audit(
                    terms,
                    st.session_state.blueprint,
                    batch_size=30,
                    progress_hook=progress_hook
                )

            st.session_state.audit_results = results

            st.success("Audit complete")

    # -----------------------------
    # RESULTS
    # -----------------------------
    if st.session_state.audit_results:
        import pandas as pd

        df = pd.DataFrame(st.session_state.audit_results)
        st.dataframe(df)

        st.metric("Total", len(df))
        st.metric("Relevant", len(df[df["classification"] == "relevant"]))
        st.metric("Irrelevant", len(df[df["classification"] == "irrelevant"]))
        st.metric("Review", len(df[df["classification"] == "review"]))

        if st.button("Continue → Export"):
            st.session_state.stage = 3
            st.rerun()


# =========================================================
# STAGE 3 — EXPORT
# =========================================================
def stage3():
    export_to_excel = load_stage3()

    st.header("📊 Export Results")

    if st.button("← Back"):
        st.session_state.stage = 2
        st.rerun()

    if not st.session_state.audit_results:
        st.info("Run audit first")
        return

    if st.button("Generate Excel"):

        with st.spinner("Building workbook..."):
            file_path = export_to_excel(
                st.session_state.audit_results,
                st.session_state.root_negatives or []
            )

        st.success("Ready")

        with open(file_path, "rb") as f:
            st.download_button(
                "Download Excel",
                f,
                file_name="ppc_audit.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )


# =========================================================
# ROUTER
# =========================================================
if st.session_state.stage == 1:
    stage1()
elif st.session_state.stage == 2:
    stage2()
elif st.session_state.stage == 3:
    stage3()
