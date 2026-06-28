import os
import io
import time
import json
from datetime import datetime
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, Client
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

st.set_page_config(
    page_title="AI-Native Spotify Discovery Engine",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Premium Minimalist Slate-Zinc CSS
st.markdown("""
    <style>
    /* Hide default sidebar elements */
    [data-testid="stSidebar"] {
        display: none !important;
    }
    [data-testid="stSidebarNav"] {
        display: none !important;
    }
    
    /* Main App Container Styling */
    .stApp {
        background-color: #09090b !important;
        color: #f4f4f5 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Elegant Title Banner */
    .app-title {
        text-align: left;
        font-size: 2.2rem;
        font-weight: 700;
        letter-spacing: -0.5px;
        color: #f4f4f5 !important;
        margin-top: 10px;
        margin-bottom: 2px;
    }
    .app-subtitle {
        text-align: left;
        font-size: 0.95rem;
        color: #a1a1aa !important;
        margin-bottom: 30px;
    }
    
    /* Custom Card Design (Minimalistic border) */
    [data-testid="stMetric"] {
        background-color: #121214 !important;
        border: 1px solid #27272a !important;
        border-radius: 8px !important;
        padding: 20px !important;
        box-shadow: none !important;
    }
    div[data-testid="stMetricValue"] {
        color: #f4f4f5 !important;
        font-weight: 700;
        font-size: 1.8rem !important;
        letter-spacing: -0.5px;
    }
    div[data-testid="stMetricLabel"] {
        color: #a1a1aa !important;
        font-weight: 500;
        font-size: 0.8rem !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    /* Custom Control Box */
    .control-box {
        background-color: #121214;
        border: 1px solid #27272a;
        border-radius: 8px;
        padding: 20px;
        margin-bottom: 20px;
    }
    .control-title {
        font-size: 1.05rem;
        font-weight: 600;
        color: #f4f4f5;
        margin-bottom: 4px;
    }
    .control-desc {
        font-size: 0.85rem;
        color: #a1a1aa;
    }
    
    /* Action Buttons (Clean Slate) */
    .stButton>button {
        background-color: #27272a !important;
        color: #f4f4f5 !important;
        border: 1px solid #3f3f46 !important;
        border-radius: 6px !important;
        font-weight: 500 !important;
        font-size: 0.85rem !important;
        padding: 8px 16px !important;
        transition: background-color 0.2s, border-color 0.2s !important;
    }
    .stButton>button:hover {
        background-color: #3f3f46 !important;
        border-color: #52525b !important;
        color: #ffffff !important;
    }
    
    /* Clean tables styling */
    div[data-testid="stDataFrame"] {
        border: 1px solid #27272a;
        border-radius: 8px;
        background-color: #121214;
    }
    div[data-testid="stMultiSelect"] > div {
        background-color: #121214 !important;
        border: 1px solid #27272a !important;
    }
    
    /* Custom scrollbars */
    ::-webkit-scrollbar {
        width: 6px;
        height: 6px;
    }
    ::-webkit-scrollbar-track {
        background: #09090b;
    }
    ::-webkit-scrollbar-thumb {
        background: #27272a;
        border-radius: 3px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: #3f3f46;
    }
    </style>
""", unsafe_allow_html=True)

from pipeline import analyze_review_with_groq

@st.cache_data(ttl=30)
def fetch_analyzed_data():
    """Fetch analyzed records from Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return get_mock_dashboard_data()
        
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        response = supabase.table("raw_feedback").select(
            "review_id, source, timestamp, text, ai_analytics(theme, sentiment, user_type, root_cause, analyzed_at)"
        ).order("timestamp", desc=True).execute()
        
        data = response.data
        if not data:
            return pd.DataFrame()
            
        rows = []
        for item in data:
            analytics = item.get("ai_analytics")
            if analytics:
                rows.append({
                    "Review ID": item["review_id"],
                    "Source": item["source"],
                    "Timestamp": item["timestamp"],
                    "Text": item["text"],
                    "Theme": analytics["theme"],
                    "Sentiment": analytics["sentiment"],
                    "User Type": analytics["user_type"],
                    "Root Cause": analytics["root_cause"],
                    "Analyzed At": analytics["analyzed_at"]
                })
        
        if not rows:
            return pd.DataFrame()
            
        df = pd.DataFrame(rows)
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], format="ISO8601")
        return df
    except Exception as e:
        st.error(f"Failed to fetch database: {str(e)}")
        return pd.DataFrame()

def get_mock_dashboard_data():
    rows = [
        {"Review ID": f"mk_{i}", "Source": "Google Play" if i % 2 == 0 else "App Store",
         "Timestamp": datetime.now() - pd.Timedelta(days=i),
         "Text": "Spotify's smart shuffle keeps repeating the same tracks. Major loop issue.",
         "Theme": "Smart Shuffle Failure", "Sentiment": "Highly Frustrated",
         "User Type": "Playlist Curator", "Root Cause": "Shuffle loops same songs repeatedly",
         "Analyzed At": datetime.now().isoformat()}
        for i in range(10)
    ]
    return pd.DataFrame(rows)

def fetch_unprocessed_count():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return 0
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        response = supabase.table("unprocessed_feedback").select("review_id", count="exact").execute()
        return len(response.data)
    except Exception:
        return 0

def run_ai_classification_in_ui():
    """Run AI classification silently in the background for all remaining reviews, updating progress."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("Supabase URL or Key not set in environment.")
        return
        
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    try:
        response = supabase.table("unprocessed_feedback").select("review_id, text").execute()
        unprocessed_records = response.data
    except Exception as e:
        st.error(f"Failed to fetch unprocessed feedback: {str(e)}")
        return
        
    if not unprocessed_records:
        st.success("🎉 All reviews are already classified!")
        return
        
    total_unprocessed = len(unprocessed_records)
    limit = min(900, total_unprocessed)
    
    progress_bar = st.progress(0.0)
    status_text = st.empty()
    
    analytics_records = []
    processed_count = 0
    delay = 3.0 if GROQ_API_KEY else 0.1
    
    for i in range(limit):
        record = unprocessed_records[i]
        review_id = record["review_id"]
        text = record["text"]
        
        status_text.markdown(f"**⚡ Classifying Review [{i+1}/{limit}]** ID: `{review_id}`")
        
        analysis = analyze_review_with_groq(text)
        
        analytics_records.append({
            "review_id": review_id,
            "theme": analysis["theme"],
            "sentiment": analysis["sentiment"],
            "user_type": analysis["user_type"],
            "root_cause": analysis["root_cause"]
        })
        
        processed_count += 1
        progress_bar.progress(float(processed_count) / float(limit))
        
        if i < limit - 1:
            time.sleep(delay)
            
    if analytics_records:
        try:
            status_text.markdown("📤 *Saving classifications to database...*")
            supabase.table("ai_analytics").upsert(analytics_records, on_conflict="review_id").execute()
            st.success(f"✅ Classification complete. Saved {processed_count} records.")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"Failed to upload analytics: {str(e)}")

def generate_excel_bytes(df):
    output = io.BytesIO()
    wb = openpyxl.Workbook()
    
    ws1 = wb.active
    ws1.title = "Analyzed Data"
    ws2 = wb.create_sheet(title="PM Pivot Summary")
    
    font_family = "Segoe UI"
    header_font = Font(name=font_family, size=11, bold=True, color="FFFFFF")
    body_font = Font(name=font_family, size=10)
    title_font = Font(name=font_family, size=14, bold=True, color="161925")
    total_font = Font(name=font_family, size=10, bold=True)
    
    header_fill = PatternFill(start_color="120F18", end_color="120F18", fill_type="solid")
    accent_fill = PatternFill(start_color="F1F2F6", end_color="F1F2F6", fill_type="solid")
    
    thin_border = Border(
        left=Side(style='thin', color='DDDDDD'),
        right=Side(style='thin', color='DDDDDD'),
        top=Side(style='thin', color='DDDDDD'),
        bottom=Side(style='thin', color='DDDDDD')
    )
    
    headers = list(df.columns)
    ws1.append(headers)
    for cell in ws1[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        
    for index, row in df.iterrows():
        row_values = list(row)
        row_values[2] = str(row_values[2])
        row_values[8] = str(row_values[8])
        ws1.append(row_values)
        
    for r in range(2, ws1.max_row + 1):
        for c in range(1, ws1.max_column + 1):
            cell = ws1.cell(row=r, column=c)
            cell.font = body_font
            cell.border = thin_border
            if c in [1, 2, 3, 5, 6, 7, 9]:
                cell.alignment = Alignment(horizontal="center")
                
    for col in ws1.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 50)
        
    ws2.views.sheetView[0].showGridLines = True
    ws2["A2"] = "Spotify Growth Analysis - Blocker vs Cohort Pivot Summary"
    ws2["A2"].font = title_font
    
    pivot = pd.crosstab(df["Theme"], df["User Type"], margins=True, margins_name="Total")
    pivot_cols = list(pivot.columns)
    
    ws2.cell(row=4, column=1, value="Theme / Cohort").font = header_font
    ws2.cell(row=4, column=1).fill = header_fill
    ws2.cell(row=4, column=1).alignment = Alignment(horizontal="center")
    
    for c_idx, col_name in enumerate(pivot_cols, start=2):
        cell = ws2.cell(row=4, column=c_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        
    for r_idx, theme_name in enumerate(pivot.index, start=5):
        cell = ws2.cell(row=r_idx, column=1, value=theme_name)
        if theme_name == "Total":
            cell.font = total_font
            cell.fill = accent_fill
        else:
            cell.font = body_font
        cell.border = thin_border
        
        for c_idx, col_name in enumerate(pivot_cols, start=2):
            val = int(pivot.loc[theme_name, col_name])
            val_cell = ws2.cell(row=r_idx, column=c_idx, value=val)
            val_cell.border = thin_border
            val_cell.alignment = Alignment(horizontal="right")
            if theme_name == "Total" or col_name == "Total":
                val_cell.font = total_font
                val_cell.fill = accent_fill
            else:
                val_cell.font = body_font
                
    for col in ws2.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws2.column_dimensions[col_letter].width = max(max_len + 5, 15)
        
    wb.save(output)
    output.seek(0)
    return output.getvalue()

# --- Dashboard Layout ---

st.markdown("<h1 class='app-title'>AI-Native Spotify Discovery Engine</h1>", unsafe_allow_html=True)
st.markdown("<p class='app-subtitle'>Diagnosing recommendation defect loops to optimize cohort engagement & retention</p>", unsafe_allow_html=True)
full_df = fetch_analyzed_data()
unprocessed_count = fetch_unprocessed_count()

# Calculate tiny overall positive stats from database
if not full_df.empty:
    total_pos = len(full_df[full_df["Theme"] == "Positive"])
    df = full_df[full_df["Theme"] != "Positive"]
else:
    total_pos = 0
    df = pd.DataFrame()

# Database Classification Controls (Clean Inline Box)
st.markdown(f"""
    <div class='control-box'>
        <div class='control-title'>Review Classification Manager</div>
        <div class='control-desc'>The pipeline has identified <b>{unprocessed_count}</b> unprocessed reviews in the database queue. Click below to start the AI classification process. Already processed reviews are skipped automatically.</div>
    </div>
""", unsafe_allow_html=True)

col_btn1, col_btn2 = st.columns([3, 1])
with col_btn2:
    if st.button("Start Classification Run"):
        if unprocessed_count == 0:
            st.warning("All records already classified.")
        else:
            with st.spinner("Processing..."):
                run_ai_classification_in_ui()
                st.rerun()
                # KPIs Calculations
if not df.empty:
    total_defects = len(df)
    highly_frustrated = len(df[df["Sentiment"] == "Highly Frustrated"])
    frustration_rate = f"{int(highly_frustrated / total_defects * 100)}%" if total_defects > 0 else "0%"
    top_defect = df["Theme"].value_counts().index[0]
else:
    total_defects = 0
    frustration_rate = "N/A"
    top_defect = "N/A"

# KPIs Grid
col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)

with col_kpi1:
    st.metric("Total Defects Ingested", total_defects, help="Total number of active product pain points/complaints")
with col_kpi2:
    st.metric("Frustration Rate", frustration_rate, help="Percentage of reviews flagged as Highly Frustrated")
with col_kpi3:
    st.metric("Primary Blocker Theme", top_defect, help="Top defect category blocking user engagement")
with col_kpi4:
    st.metric("Positive Sentiment (Overall)", total_pos, help="Total satisfied reviews (kept in Excel for further exploration)")
 
st.markdown("<br>", unsafe_allow_html=True)
 
# Collapsible Filtering Matrix (Expander - Clean Layout)
with st.expander("Filter Matrix", expanded=False):
    if not df.empty:
        source_opts = list(df["Source"].unique())
        theme_opts = list(df["Theme"].unique())
        user_opts = list(df["User Type"].unique())
        sentiment_opts = list(df["Sentiment"].unique())
    else:
        source_opts, theme_opts, user_opts, sentiment_opts = [], [], [], []
        
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    with f_col1:
        source_filter = st.multiselect("Source", options=source_opts, default=source_opts)
    with f_col2:
        theme_filter = st.multiselect("Blocker Theme", options=theme_opts, default=theme_opts)
    with f_col3:
        user_filter = st.multiselect("User Cohort", options=user_opts, default=user_opts)
    with f_col4:
        sentiment_filter = st.multiselect("Sentiment Severity", options=sentiment_opts, default=sentiment_opts)
        
    search_query = st.text_input("Search Text Content", "")
 
# Apply Filters
if not df.empty:
    filtered_df = df[
        (df["Source"].isin(source_filter)) &
        (df["Theme"].isin(theme_filter)) &
        (df["User Type"].isin(user_filter)) &
        (df["Sentiment"].isin(sentiment_filter))
    ]
    if search_query:
        filtered_df = filtered_df[filtered_df["Text"].str.contains(search_query, case=False, na=False)]
else:
    filtered_df = pd.DataFrame()
 
# Visualizations
st.subheader("📊 Defect Diagnostics & User Cohorts")
col_chart1, col_chart2, col_chart3 = st.columns(3)
 
with col_chart1:
    st.markdown("**Blocker Themes Distribution**")
    if not filtered_df.empty:
        theme_counts = filtered_df["Theme"].value_counts().reset_index()
        theme_counts.columns = ["Theme", "Count"]
        st.bar_chart(theme_counts.set_index("Theme"))
    else:
        st.info("No data matches active filters.")
 
with col_chart2:
    st.markdown("**Sentiment Severity Distribution**")
    if not filtered_df.empty:
        sentiment_counts = filtered_df["Sentiment"].value_counts().reset_index()
        sentiment_counts.columns = ["Sentiment", "Count"]
        st.bar_chart(sentiment_counts.set_index("Sentiment"))
    else:
        st.info("No data matches active filters.")
 
with col_chart3:
    st.markdown("**User Cohorts Affected**")
    if not filtered_df.empty:
        cohort_counts = filtered_df["User Type"].value_counts().reset_index()
        cohort_counts.columns = ["Cohort", "Count"]
        st.bar_chart(cohort_counts.set_index("Cohort"))
    else:
        st.info("No data matches active filters.")
 
# Pivot Matrix & Report Download
col_pivot, col_down = st.columns([3, 1])
 
with col_pivot:
    st.subheader("🎲 Theme vs Segment Cross-Tabulation")
    if not filtered_df.empty:
        pivot_df = pd.crosstab(filtered_df["Theme"], filtered_df["User Type"], margins=True, margins_name="Total")
        st.dataframe(pivot_df, use_container_width=True)
    else:
        st.info("No defect records to formulate cross-tabs.")
 
with col_down:
    st.subheader("📥 Export Data")
    st.markdown("Download a fully formatted Excel report containing raw records and PM pivot sheets (includes positive reviews).")
    
    # Formulate export DataFrame including both filtered defects and matching positive reviews
    if not full_df.empty:
        filtered_pos = full_df[
            (full_df["Theme"] == "Positive") &
            (full_df["Source"].isin(source_filter))
        ]
        if search_query and not filtered_pos.empty:
            filtered_pos = filtered_pos[filtered_pos["Text"].str.contains(search_query, case=False, na=False)]
        export_df = pd.concat([filtered_df, filtered_pos]) if not filtered_df.empty else filtered_pos
    else:
        export_df = pd.DataFrame()

    if not export_df.empty:
        excel_binary = generate_excel_bytes(export_df)
        st.download_button(
            label="💾 DOWNLOAD EXCEL REPORT",
            data=excel_binary,
            file_name=f"Spotify_Growth_Metrics_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.button("💾 DOWNLOAD EXCEL REPORT", disabled=True)
 
st.markdown("<br>", unsafe_allow_html=True)
 
# Data Table Grid
st.subheader("📋 Classified Reviews Feed")
if not filtered_df.empty:
    st.dataframe(
        filtered_df[["Timestamp", "Source", "Theme", "Sentiment", "User Type", "Root Cause", "Text"]],
        use_container_width=True,
        column_config={
            "Timestamp": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            "Text": st.column_config.TextColumn(width="large")
        }
    )
else:
    st.warning("No records match the active filter configurations.")
