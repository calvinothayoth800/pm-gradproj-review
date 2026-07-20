import os
import io
import time
import json
from datetime import datetime
import pandas as pd
import streamlit as st
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from dotenv import load_dotenv

import db_client
import scrapers
import query_strategist
import open_coding
import taxonomy_synthesizer
import classifier
import auditor
import orchestrator

load_dotenv()

# Set Streamlit Page Configuration
st.set_page_config(
    page_title="Blinkit Category-Discovery Engine",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom Styling (Charcoal dark mode with slate-green and soft yellow highlights matching Blinkit branding)
st.markdown("""
    <style>
    /* Hide sidebar nav */
    [data-testid="stSidebar"] {
        display: none !important;
    }
    
    /* Main App Container Styling */
    .stApp {
        background-color: #0b0f19 !important;
        color: #e2e8f0 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Elegant Title Banner */
    .app-title {
        text-align: left;
        font-size: 2.3rem;
        font-weight: 700;
        letter-spacing: -0.5px;
        color: #ffcc00 !important;
        margin-top: 10px;
        margin-bottom: 2px;
    }
    .app-subtitle {
        text-align: left;
        font-size: 1.0rem;
        color: #00b560 !important;
        font-weight: 500;
        margin-bottom: 25px;
    }
    
    /* Metric Cards */
    [data-testid="stMetric"] {
        background-color: #111827 !important;
        border: 1px solid #1f2937 !important;
        border-radius: 8px !important;
        padding: 20px !important;
    }
    div[data-testid="stMetricValue"] {
        color: #f3f4f6 !important;
        font-weight: 700;
        font-size: 1.8rem !important;
    }
    div[data-testid="stMetricLabel"] {
        color: #9ca3af !important;
        font-weight: 500;
        font-size: 0.8rem !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    /* Buttons */
    .stButton>button {
        background-color: #1e293b !important;
        color: #ffffff !important;
        border: 1px solid #334155 !important;
        border-radius: 6px !important;
        font-weight: 500 !important;
        font-size: 0.85rem !important;
        padding: 8px 16px !important;
        transition: all 0.2s ease !important;
    }
    .stButton>button:hover {
        background-color: #00b560 !important;
        border-color: #00e676 !important;
        color: #ffffff !important;
    }
    
    /* Ingestion Alert dialog or container styling */
    div[data-testid="stNotification"] {
        background-color: #1e293b !important;
        border: 1px solid #334155 !important;
        border-radius: 8px !important;
        color: #ffffff !important;
    }
    
    /* Dataframes */
    div[data-testid="stDataFrame"] {
        border: 1px solid #1f2937;
        border-radius: 8px;
        background-color: #111827;
    }
    </style>
""", unsafe_allow_html=True)

# Helper to load dataset
@st.cache_data(ttl=5)
def get_dashboard_data():
    return db_client.fetch_analyzed_data()

# Helper to generate Excel Sheet using openpyxl
def generate_excel_bytes(df):
    output = io.BytesIO()
    wb = openpyxl.Workbook()
    
    ws1 = wb.active
    ws1.title = "Raw Ingestion & Analytics"
    ws2 = wb.create_sheet(title="PM Pivot Summary")
    
    font_family = "Segoe UI"
    header_font = Font(name=font_family, size=11, bold=True, color="FFFFFF")
    body_font = Font(name=font_family, size=10)
    title_font = Font(name=font_family, size=14, bold=True, color="00b560")
    total_font = Font(name=font_family, size=10, bold=True)
    
    header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    accent_fill = PatternFill(start_color="F3F4F6", end_color="F3F4F6", fill_type="solid")
    
    thin_border = Border(
        left=Side(style='thin', color='DDDDDD'),
        right=Side(style='thin', color='DDDDDD'),
        top=Side(style='thin', color='DDDDDD'),
        bottom=Side(style='thin', color='DDDDDD')
    )
    
    # Raw Data sheet headers and rows
    headers = list(df.columns)
    ws1.append(headers)
    for cell in ws1[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        
    for index, row in df.iterrows():
        row_values = [str(val) if val is not None else "" for val in row]
        ws1.append(row_values)
        
    for r in range(2, ws1.max_row + 1):
        for c in range(1, ws1.max_column + 1):
            cell = ws1.cell(row=r, column=c)
            cell.font = body_font
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center" if c != 4 else "left")
            
    # Auto-adjust column widths
    for col in ws1.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 50)
        
    # Pivot sheet
    ws2.views.sheetView[0].showGridLines = True
    ws2["A2"] = "Blinkit Category-Discovery PM Pivot Report"
    ws2["A2"].font = title_font
    
    # Cross-tab table of Theme vs User Cohort
    if not df.empty:
        pivot = pd.crosstab(df["Theme"], df["User Type"], margins=True, margins_name="Total")
        
        ws2.cell(row=4, column=1, value="Theme vs Cohort Distribution").font = Font(name=font_family, size=12, bold=True)
        
        # Write headers
        ws2.cell(row=6, column=1, value="Theme / Cohort").font = header_font
        ws2.cell(row=6, column=1).fill = header_fill
        
        for col_idx, col_name in enumerate(pivot.columns, start=2):
            cell = ws2.cell(row=6, column=col_idx, value=col_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
            
        # Write rows
        current_row = 7
        for theme_name in pivot.index:
            cell = ws2.cell(row=current_row, column=1, value=theme_name)
            if theme_name == "Total":
                cell.font = total_font
                cell.fill = accent_fill
            else:
                cell.font = body_font
            cell.border = thin_border
            
            for col_idx, col_name in enumerate(pivot.columns, start=2):
                val = int(pivot.loc[theme_name, col_name])
                val_cell = ws2.cell(row=current_row, column=col_idx, value=val)
                val_cell.border = thin_border
                val_cell.alignment = Alignment(horizontal="right")
                if theme_name == "Total" or col_name == "Total":
                    val_cell.font = total_font
                    val_cell.fill = accent_fill
                else:
                    val_cell.font = body_font
            current_row += 1
            
    for col in ws2.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws2.column_dimensions[col_letter].width = max(max_len + 5, 18)
        
    wb.save(output)
    output.seek(0)
    return output.getvalue()

# Dashboard Title
st.markdown("<h1 class='app-title'>Blinkit Category-Discovery Intelligence Engine</h1>", unsafe_allow_html=True)
st.markdown("<p class='app-subtitle'>Multi-Agent Analytical Pipeline diagnosing quick-commerce browse & category explore issues</p>", unsafe_allow_html=True)

# Fetch latest database records
df = get_dashboard_data()
unprocessed_count = len(db_client.fetch_unprocessed_feedback())

# Check status of local vs supabase
db_status_color = "#00b560" if not db_client._USE_LOCAL_SQLITE else "#ff9900"
db_status_text = "Supabase Live Mode" if not db_client._USE_LOCAL_SQLITE else "SQLite Local Simulation Mode"
st.markdown(f"<div style='font-size: 0.85rem; margin-bottom: 20px; font-weight: 500;'>Database Connection: <span style='color:{db_status_color};'>{db_status_text}</span></div>", unsafe_allow_html=True)

# ----------------------------------------------------
# Multi-Agent Phase Controller Panel
# ----------------------------------------------------
st.subheader("⚡ Multi-Agent Pipeline Control Console")

col_c1, col_c2, col_c3 = st.columns(3)

with col_c1:
    with st.container(border=True):
        st.write("### Phase 1 & 2")
        st.write("Trigger scrapers & keywords strategist")
        if st.button("🚀 Run Ingestion & Strategy", use_container_width=True):
            st.info("Scraping App Store, Play Store, and Reddit threads...")
            db_client.log_pipeline_run("Phase 1: Ingestion", "STARTED")
            play_records = scrapers.scrape_play_store(limit=50)
            app_records = scrapers.scrape_app_store(limit=50)
            reddit_records = scrapers.scrape_reddit()
            all_ingested = play_records + app_records + reddit_records
            
            # Validate
            is_valid, msg = orchestrator.validate_ingestion(all_ingested)
            if is_valid:
                db_client.insert_raw_feedback(all_ingested)
                db_client.log_pipeline_run("Phase 1: Ingestion", "COMPLETED", len(all_ingested))
                st.success(f"Ingested {len(all_ingested)} reviews!")
                
                # Propose keywords
                db_client.log_pipeline_run("Phase 2: Query Strategist", "STARTED")
                keywords = query_strategist.run_query_strategist(all_ingested[:100])
                db_client.log_pipeline_run("Phase 2: Query Strategist", "COMPLETED", len(keywords))
                st.success(f"Suggested keywords: {', '.join(keywords[:6])}...")
                st.rerun()
            else:
                db_client.log_pipeline_run("Phase 1: Ingestion", "FAILED", metadata={"error": msg})
                st.error(f"Validation failure: {msg}")

with col_c2:
    with st.container(border=True):
        st.write("### Phase 3 & 4")
        st.write("Run unconstrained coding & synthesize taxonomy")
        if st.button("🔍 Synthesize Category Taxonomy", use_container_width=True):
            st.info("Extracting themes from raw reviews sample...")
            raw_feedback_rows = db_client.fetch_unprocessed_feedback(limit=300)
            if not raw_feedback_rows:
                # If database empty, populate from simulated scrapers
                raw_feedback_rows = scrapers.get_simulated_scraped_data("Google Play") + scrapers.get_simulated_scraped_data("App Store")
                db_client.insert_raw_feedback(raw_feedback_rows)
                
            db_client.log_pipeline_run("Phase 3: Open Coding", "STARTED")
            themes = open_coding.run_open_coding(raw_feedback_rows)
            db_client.log_pipeline_run("Phase 3: Open Coding", "COMPLETED", len(themes))
            
            db_client.log_pipeline_run("Phase 4: Taxonomy Synthesizer", "STARTED")
            proposal = taxonomy_synthesizer.run_taxonomy_synthesis(themes, raw_feedback_rows)
            st.success("Proposed taxonomy generated successfully!")
            st.rerun()

with col_c3:
    with st.container(border=True):
        st.write("### Phase 5 & 6")
        st.write(f"Classify and audit delta queue ({unprocessed_count} unprocessed)")
        
        # Load taxonomy to see if approved
        prop = taxonomy_synthesizer.load_taxonomy_proposal()
        taxonomy_approved = prop.get("approved", False) if prop else False
        
        if not taxonomy_approved:
            st.warning("⚠️ Taxonomy not approved. Approve the proposed taxonomy below first.")
            st.button("🚀 Run Classification", disabled=True, use_container_width=True)
        else:
            if st.button("🚀 Run Classification & Auditing", use_container_width=True):
                st.info("Classifying and auditing queue...")
                categories = [c["name"] for c in prop["categories"]]
                
                # Fetch unprocessed
                unprocessed_records = db_client.fetch_unprocessed_feedback(limit=900)
                if not unprocessed_records:
                    st.warning("No unprocessed records in database.")
                else:
                    db_client.log_pipeline_run("Phase 5: Classifier", "STARTED")
                    classified = []
                    for i, r in enumerate(unprocessed_records):
                        res = classifier.classify_review(r["text"], categories)
                        res["review_id"] = r["review_id"]
                        res["text"] = r["text"]
                        classified.append(res)
                    
                    is_valid, msg = orchestrator.validate_classification(classified, categories)
                    if is_valid:
                        db_client.insert_ai_analytics(classified)
                        db_client.log_pipeline_run("Phase 5: Classifier", "COMPLETED", len(classified))
                        
                        # Run auditor
                        db_client.log_pipeline_run("Phase 6: Auditor", "STARTED")
                        rate, audited = auditor.run_auditor(classified, categories)
                        db_client.log_pipeline_run("Phase 6: Auditor", "COMPLETED", len(audited), {"agreement_rate": rate})
                        
                        st.success(f"Successfully classified {len(classified)} records! Agreement rate: {rate:.1%}")
                        st.rerun()
                    else:
                        db_client.log_pipeline_run("Phase 5: Classifier", "FAILED", metadata={"error": msg})
                        st.error(f"Classification validation failed: {msg}")

# ----------------------------------------------------
# Human Checkpoint Widget: Taxonomy Approval (Phase 4)
# ----------------------------------------------------
prop = taxonomy_synthesizer.load_taxonomy_proposal()
if prop and not prop.get("approved"):
    st.markdown("<br>", unsafe_allow_html=True)
    st.warning("🔴 **Human Checkpoint: Category Taxonomy Approval Required**")
    with st.container(border=True):
        st.write("The Taxonomy Synthesizer proposed the following category taxonomy. Review and approve to proceed with classification:")
        
        for c in prop.get("categories", []):
            st.write(f"- **{c['name']}**: {c['description']}")
            st.write(f"  *Example Quote: \"{c['examples'][0]}\"*")
            
        if st.button("💚 Approve Proposed Taxonomy & Resume Pipeline", use_container_width=True):
            prop["approved"] = True
            taxonomy_synthesizer.save_taxonomy_proposal(prop)
            st.success("Taxonomy successfully approved! The classifier is now unlocked.")
            st.rerun()

# ----------------------------------------------------
# KPIs & Analytical Metrics
# ----------------------------------------------------
st.markdown("<hr style='border:0; border-top:1px solid #1f2937; margin:20px 0;'>", unsafe_allow_html=True)
st.subheader("📊 Key Exploration Insights & Metrics")

if not df.empty:
    total_reviews = len(df)
    frustrated_pct = len(df[df["Sentiment"].isin(["Highly Frustrated", "Disappointed"])]) / total_reviews if total_reviews > 0 else 0
    top_theme = df["Theme"].value_counts().index[0] if total_reviews > 0 else "N/A"
    
    # Inter-agent agreement rate from pipeline run logs
    runs = db_client.fetch_pipeline_runs(10)
    auditor_runs = [r for r in runs if r["phase"] == "Phase 6: Auditor" and r["status"] == "COMPLETED"]
    if auditor_runs:
        last_val = json.loads(auditor_runs[0]["validation_results"]) if isinstance(auditor_runs[0]["validation_results"], str) else auditor_runs[0]["validation_results"]
        agreement_rate = f"{last_val.get('agreement_rate', 0.0):.1%}" if last_val else "N/A"
    else:
        agreement_rate = "90.0% (Simulated)"
        
    # Spot-check validity calculation
    spot_checked_df = df[df["Spot Checked"] == True]
    valid_spot_checked = spot_checked_df[spot_checked_df["Spot Check Valid"] == True]
    if len(spot_checked_df) > 0:
        spot_check_rate = f"{len(valid_spot_checked) / len(spot_checked_df):.1%}"
    else:
        spot_check_rate = "N/A (Awaiting Check)"
else:
    total_reviews = 0
    frustrated_pct = 0
    top_theme = "N/A"
    agreement_rate = "N/A"
    spot_check_rate = "N/A"

kpi_c1, kpi_c2, kpi_c3, kpi_c4 = st.columns(4)
with kpi_c1:
    st.metric("Reviews Classified", total_reviews)
with kpi_c2:
    st.metric("User Frustration Rate", f"{frustrated_pct:.1%}")
with kpi_c3:
    st.metric("Primary explore pain point", top_theme)
with kpi_c4:
    st.metric("Auditor Agreement Rate", agreement_rate)

# ----------------------------------------------------
# Visualizations
# ----------------------------------------------------
if not df.empty:
    col_chart1, col_chart2 = st.columns(2)
    with col_chart1:
        st.markdown("**Category explore Pain Points Distribution**")
        theme_counts = df["Theme"].value_counts().reset_index()
        theme_counts.columns = ["Theme", "Count"]
        st.bar_chart(theme_counts.set_index("Theme"))
    with col_chart2:
        st.markdown("**Affected User Cohort Segments**")
        cohort_counts = df["User Type"].value_counts().reset_index()
        cohort_counts.columns = ["Cohort", "Count"]
        st.bar_chart(cohort_counts.set_index("Cohort"))

# ----------------------------------------------------
# Human Checkpoint: Manual Spot Check Console (Phase 6)
# ----------------------------------------------------
st.markdown("<hr style='border:0; border-top:1px solid #1f2937; margin:20px 0;'>", unsafe_allow_html=True)
st.subheader("🎯 Phase 6 Checkpoint: Human Spot-Checking Console")

# Fetch records flagged for spot check where validation has not been decided yet
spot_check_queue = df[(df["Spot Checked"] == True) & (df["Spot Check Valid"].isna())]

if spot_check_queue.empty:
    st.info("🎉 All spot checks are complete. No pending records to verify.")
else:
    st.write(f"The Auditor flagged {len(spot_check_queue)} records for validation. Please confirm if the classification is correct:")
    
    current_check = spot_check_queue.iloc[0]
    review_id = current_check["Review ID"]
    
    with st.container(border=True):
        st.write(f"**Review Text:** \"{current_check['Text']}\"")
        st.write(f"**Source:** {current_check['Source']} | **App Version:** {current_check['App Version']}")
        st.write(f"**AI Theme Classification:** `{current_check['Theme']}`")
        st.write(f"**AI Sentiment Classification:** `{current_check['Sentiment']}`")
        st.write(f"**AI Cohort Classification:** `{current_check['User Type']}`")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("✅ Confirm Classification as Valid", use_container_width=True):
                db_client.update_spot_check(review_id, True)
                st.success("Validated classification!")
                st.cache_data.clear()
                st.rerun()
        with col_btn2:
            if st.button("❌ Flag Classification as Invalid", use_container_width=True):
                db_client.update_spot_check(review_id, False)
                st.warning("Flagged classification as incorrect.")
                st.cache_data.clear()
                st.rerun()

# Display spot check stats
if total_reviews > 0:
    st.write(f"**Human Spot-Check Agreement Rate:** {spot_check_rate} (Valid spot-checks out of completed checks)")

# ----------------------------------------------------
# Export & Reporting Container
# ----------------------------------------------------
st.markdown("<hr style='border:0; border-top:1px solid #1f2937; margin:20px 0;'>", unsafe_allow_html=True)
st.subheader("📥 Export Reports")

with st.container(border=True):
    col_d1, col_d2 = st.columns([3, 1])
    with col_d1:
        st.markdown("<p style='margin:0; font-size:0.9rem; color:#9ca3af;'>Generate a comprehensive Microsoft Excel report. Includes all raw feedback, metadata columns, and a cross-tabulated <b>PM Pivot Summary</b> sheet comparing Dynamic Themes vs User Cohort segments.</p>", unsafe_allow_html=True)
    with col_d2:
        if not df.empty:
            excel_bin = generate_excel_bytes(df)
            st.download_button(
                label="💾 DOWNLOAD EXCEL REPORT",
                data=excel_bin,
                file_name=f"Blinkit_Category_Discovery_Metrics_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.button("💾 DOWNLOAD EXCEL REPORT", disabled=True, use_container_width=True)

# ----------------------------------------------------
# Classified Feed
# ----------------------------------------------------
st.markdown("<hr style='border:0; border-top:1px solid #1f2937; margin:20px 0;'>", unsafe_allow_html=True)
st.subheader("📋 Classified Reviews Feed")
if not df.empty:
    st.dataframe(
        df[["Timestamp", "Source", "App Version", "Theme", "Sentiment", "User Type", "Root Cause", "Text"]],
        use_container_width=True,
        column_config={
            "Timestamp": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            "Text": st.column_config.TextColumn(width="large")
        }
    )
else:
    st.info("No records classified yet. Run the pipeline control panel above to populate analytics.")
