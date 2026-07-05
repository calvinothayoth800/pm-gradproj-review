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
    
    /* Action Buttons (Clean Slate) */
    .stButton>button {
        background-color: #18181b !important;
        color: #fafafa !important;
        border: 1px solid #27272a !important;
        border-radius: 6px !important;
        font-weight: 500 !important;
        font-size: 0.85rem !important;
        padding: 6px 12px !important;
        transition: all 0.15s ease !important;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
    }
    .stButton>button:hover {
        background-color: #27272a !important;
        border-color: #3f3f46 !important;
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
    
    /* Input Fields (Text Inputs, Selectboxes) */
    div[data-testid="stTextInput"] > div > div > input {
        background-color: #121214 !important;
        color: #f4f4f5 !important;
        border: 1px solid #27272a !important;
        border-radius: 6px !important;
    }
    
    /* Sleek Linear-style white progress bar */
    div[data-testid="stProgress"] > div > div > div > div {
        background-color: #fafafa !important;
    }
    div[data-testid="stProgress"] {
        padding-top: 10px !important;
        padding-bottom: 10px !important;
    }
    
    /* Style Alert/Notification Boxes to match dark theme */
    div[data-testid="stNotification"] {
        background-color: #18181b !important;
        border: 1px solid #27272a !important;
        border-radius: 8px !important;
        color: #f4f4f5 !important;
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

import pipeline
from pipeline import analyze_review_with_groq, scrape_app_store, scrape_google_play, scrape_reddit

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
    
    batch_size = 10
    analytics_records = []
    processed_count = 0
    delay = 3.0 if GROQ_API_KEY else 0.1
    
    for i in range(limit):
        record = unprocessed_records[i]
        review_id = record["review_id"]
        text = record["text"]
        
        saved_so_far = processed_count - len(analytics_records)
        status_text.markdown(f"**⚡ Classifying Review [{i+1}/{limit}]** ID: `{review_id}` *(Saved to DB: {saved_so_far})*")
        
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
        
        # Progressive batch upload to avoid timeout data loss
        if len(analytics_records) >= batch_size or i == limit - 1:
            try:
                supabase.table("ai_analytics").upsert(analytics_records, on_conflict="review_id").execute()
                analytics_records = []  # Reset batch buffer
            except Exception as e:
                st.error(f"Failed to upload current batch: {str(e)}")
                return
                
        if i < limit - 1:
            time.sleep(delay)
            
    st.success(f"✅ Classification complete. Saved {processed_count} records.")
    st.cache_data.clear()

def run_scraping_in_ui(demo_mode=False):
    """Run scraper loop in Streamlit and save new matching reviews to Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("Supabase credentials not configured in environment variables.")
        return
        
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    st.info("🔄 Connecting to App Store, Reddit, and Google Play Store...")
    status_text = st.empty()
    
    # Ingestion List
    all_scraped = []
    
    # 1. App Store
    status_text.markdown("🌐 **Apple App Store**: Fetching recent reviews for Spotify...")
    app_store_reviews = scrape_app_store(app_id="324684580", source="App Store")
    all_scraped.extend(app_store_reviews)
    
    # 2. Reddit
    status_text.markdown("🌐 **Reddit**: Fetching search results on r/spotify...")
    reddit_reviews = scrape_reddit(subreddit="spotify", source="Reddit")
    all_scraped.extend(reddit_reviews)
    
    # 3. Google Play
    status_text.markdown("🌐 **Google Play Store**: Fetching reviews for com.spotify.music...")
    google_play_reviews = scrape_google_play(app_id="com.spotify.music", source="Google Play")
    all_scraped.extend(google_play_reviews)
    
    # If demo mode is active, inject 3 fresh target reviews to guarantee queue expansion
    if demo_mode:
        import hashlib
        import random
        from datetime import datetime, timezone
        
        DEMO_TEMPLATES = [
            "Spotify's smart shuffle keeps repeating the same tracks. I hate this new algorithm update.",
            "The recommendation algorithm has turned my feed into a complete echo chamber. No new music at all.",
            "Is anyone else experiencing a bad loop of the same 10 tracks on shuffle? It is so annoying.",
            "I turned on shuffle hoping for some good discovery, but the recommendation engine keeps playing the same songs.",
            "The Spotify algorithm feature is a major failure. It keeps looping identical songs repeatedly.",
            "Terrible music discovery on Spotify. It keeps playing the same loop of songs instead of new recommendations."
        ]
        
        status_text.markdown("🔧 **Demo Mode**: Injecting fresh reviews to guarantee queue expansion...")
        for i in range(3):
            text = random.choice(DEMO_TEMPLATES) + f" (Demo ID: {int(time.time())}_{i})"
            platform_id = f"demo_review_{int(time.time())}_{i}"
            hasher = hashlib.md5()
            hasher.update(f"Google Play:{platform_id}".encode("utf-8"))
            all_scraped.append({
                "review_id": hasher.hexdigest(),
                "source": "Google Play",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "text": text
            })
            
    if not all_scraped:
        status_text.markdown("⚠️ *No reviews matching target keywords were found in current store updates.*")
        return
        
    status_text.markdown(f"📥 *Syncing {len(all_scraped)} matching reviews to Supabase...*")
    
    try:
        supabase.table("raw_feedback").upsert(all_scraped, on_conflict="review_id").execute()
        st.success(f"✅ Ingestion successful. Scraped and synchronized {len(all_scraped)} reviews (duplicates automatically merged by Postgres PK).")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Failed to upsert scraped reviews: {str(e)}")

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
    ws2["A2"] = "Spotify Growth Analysis - Executive PM Report"
    ws2["A2"].font = title_font
    
    pos_themes = ["Accurate Recommendations", "Great UI/UX", "Smart Curation", "Positive"]
    neg_df = df[~df["Theme"].isin(pos_themes)]
    pos_df = df[df["Theme"].isin(pos_themes)]
    
    if not neg_df.empty:
        pivot_neg = pd.crosstab(neg_df["Theme"], neg_df["User Type"], margins=True, margins_name="Total")
    else:
        pivot_neg = pd.DataFrame()
        
    if not pos_df.empty:
        pivot_pos = pd.crosstab(pos_df["Theme"], pos_df["User Type"], margins=True, margins_name="Total")
    else:
        pivot_pos = pd.DataFrame()

    def write_pivot_table(ws, pivot, start_row, title):
        # Write section title
        ws.cell(row=start_row, column=1, value=title).font = Font(name=font_family, size=12, bold=True, color="161925")
        
        if pivot.empty:
            ws.cell(row=start_row + 1, column=1, value="No records available for this section.").font = body_font
            return start_row + 3
            
        pivot_cols = list(pivot.columns)
        
        # Write headers
        ws.cell(row=start_row + 2, column=1, value="Theme / Cohort").font = header_font
        ws.cell(row=start_row + 2, column=1).fill = header_fill
        ws.cell(row=start_row + 2, column=1).alignment = Alignment(horizontal="center", vertical="center")
        
        for c_idx, col_name in enumerate(pivot_cols, start=2):
            cell = ws.cell(row=start_row + 2, column=c_idx, value=col_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            
        # Write rows
        current_row = start_row + 3
        for theme_name in pivot.index:
            cell = ws.cell(row=current_row, column=1, value=theme_name)
            if theme_name == "Total":
                cell.font = total_font
                cell.fill = accent_fill
            else:
                cell.font = body_font
            cell.border = thin_border
            
            for c_idx, col_name in enumerate(pivot_cols, start=2):
                val = int(pivot.loc[theme_name, col_name])
                val_cell = ws.cell(row=current_row, column=c_idx, value=val)
                val_cell.border = thin_border
                val_cell.alignment = Alignment(horizontal="right", vertical="center")
                if theme_name == "Total" or col_name == "Total":
                    val_cell.font = total_font
                    val_cell.fill = accent_fill
                else:
                    val_cell.font = body_font
            current_row += 1
            
        return current_row + 2

    # Write tables
    next_row = 4
    next_row = write_pivot_table(ws2, pivot_neg, next_row, "🚨 Section 1: Blocker & Defect Themes vs User Cohort")
    next_row = write_pivot_table(ws2, pivot_pos, next_row, "💚 Section 2: Customer Satisfaction & Positive Features vs User Cohort")
    
    for col in ws2.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws2.column_dimensions[col_letter].width = max(max_len + 5, 18)
        
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
    pos_themes = ["Accurate Recommendations", "Great UI/UX", "Smart Curation", "Positive"]
    total_pos = len(full_df[full_df["Theme"].isin(pos_themes)])
    df = full_df[~full_df["Theme"].isin(pos_themes)]
else:
    total_pos = 0
    df = pd.DataFrame()

# Initialize session state for classification and scraping runs
if "run_classification" not in st.session_state:
    st.session_state.run_classification = False
if "run_scraping" not in st.session_state:
    st.session_state.run_scraping = False
if "active_keywords" not in st.session_state:
    st.session_state.active_keywords = [
        "discovery", "recommendation", "smart shuffle", "shuffle", "algorithm", 
        "same songs", "echo chamber", "loop", "repeat", "ad", "ads", "slow", 
        "sluggish", "slop", "ai dj", "dj", "widget", "ui", "ux", "clutter", 
        "bugs", "glitch", "premium"
    ]
if "show_settings" not in st.session_state:
    st.session_state.show_settings = False
if "show_no_reviews_dialog" not in st.session_state:
    st.session_state.show_no_reviews_dialog = False

# Synchronize in-memory pipeline keywords configuration with UI settings
pipeline.KEYWORDS = st.session_state.active_keywords

# 1. Ingestion settings dialog trigger
if st.session_state.show_settings:
    try:
        @st.dialog("⚙️ Ingestion Filter Settings")
        def show_settings_dialog():
            st.write("Edit keywords to filter Spotify reviews (click 'x' to remove a tag):")
            
            # Use st.multiselect to display and allow direct tag deletion in one compact element!
            updated_tags = st.multiselect(
                "Active Keyword Filter Tags:",
                options=sorted(list(set(st.session_state.active_keywords))),
                default=st.session_state.active_keywords,
                label_visibility="collapsed"
            )
            
            # Save selection to state
            st.session_state.active_keywords = updated_tags
            
            # Add New Tag row
            col_add, col_btn = st.columns([3, 1])
            with col_add:
                new_tag = st.text_input("Add Tag", placeholder="e.g. lyrics, search", label_visibility="collapsed", key="add_tag_modal")
            with col_btn:
                if st.button("➕ Add", use_container_width=True):
                    if new_tag and new_tag.lower().strip() not in st.session_state.active_keywords:
                        st.session_state.active_keywords.append(new_tag.lower().strip())
                        st.rerun()
                        
            st.markdown("<hr style='border:0; border-top:1px solid #27272a; margin:12px 0;'>", unsafe_allow_html=True)
            if st.button("Save & Apply Settings", use_container_width=True):
                pipeline.KEYWORDS = st.session_state.active_keywords
                st.session_state.show_settings = False
                st.rerun()
                
        show_settings_dialog()
    except AttributeError:
        # Fallback container for older Streamlit versions < 1.34.0 (renders inline modal overlay at top of page)
        st.markdown("<div style='background-color:#110f18; padding:15px; border-radius:8px; border:1px solid #d4af37; margin-bottom:20px;'>", unsafe_allow_html=True)
        st.markdown("<h4 style='color:#d4af37; margin-top:0;'>⚙️ Ingestion Filter Settings</h4>", unsafe_allow_html=True)
        st.write("Edit keywords to filter Spotify reviews:")
        
        updated_tags = st.multiselect(
            "Active Keyword Filter Tags (Fallback):",
            options=sorted(list(set(st.session_state.active_keywords))),
            default=st.session_state.active_keywords,
            key="fb_ms"
        )
        st.session_state.active_keywords = updated_tags
        
        col_add, col_btn = st.columns([3, 1])
        with col_add:
            new_tag = st.text_input("Add Tag", placeholder="e.g. lyrics", label_visibility="collapsed", key="add_tag_fb")
        with col_btn:
            if st.button("➕ Add", key="add_btn_fb", use_container_width=True):
                if new_tag and new_tag.lower().strip() not in st.session_state.active_keywords:
                    st.session_state.active_keywords.append(new_tag.lower().strip())
                    st.rerun()
                    
        if st.button("Save & Dismiss Settings", use_container_width=True):
            pipeline.KEYWORDS = st.session_state.active_keywords
            st.session_state.show_settings = False
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

# 2. Search status dialog viewer trigger
if st.session_state.show_no_reviews_dialog:
    try:
        @st.dialog("🔍 Ingestion Alert: No New Reviews")
        def show_no_reviews_dialog():
            st.markdown("<p style='font-size:0.95rem; font-weight: 500; color:#fafafa;'>All reviews for the below tags scraped, no new reviews. For testing purposes, please enable the Demo Ingestion toggle.</p>", unsafe_allow_html=True)
            st.write("**Active Search Tags:**")
            st.write(", ".join(f"`{k}`" for k in st.session_state.active_keywords))
            if st.button("Dismiss Alert", use_container_width=True):
                st.session_state.show_no_reviews_dialog = False
                st.rerun()
        show_no_reviews_dialog()
    except AttributeError:
        # Fallback for Streamlit < 1.34.0
        st.markdown("<div style='background-color:#110f18; padding:15px; border-radius:8px; border:1px solid #d4af37; margin-bottom:20px;'>", unsafe_allow_html=True)
        st.markdown("<h4 style='color:#d4af37; margin-top:0;'>🔍 Ingestion Alert: No New Reviews</h4>", unsafe_allow_html=True)
        st.write("All reviews for the below tags scraped, no new reviews. For testing purposes, please enable the Demo Ingestion toggle.")
        st.write("**Active Search Tags:**")
        st.write(", ".join(f"`{k}`" for k in st.session_state.active_keywords))
        if st.button("Dismiss Alert", use_container_width=True):
            st.session_state.show_no_reviews_dialog = False
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

# Database Classification Controls (Clean Open Layout)
try:
    col_desc, col_btn = st.columns([3, 1], vertical_alignment="center")
except TypeError:
    col_desc, col_btn = st.columns([3, 1])

with col_desc:
    st.markdown("<h3 style='margin:0; font-size:1.15rem; font-weight:600; color:#fafafa;'>⚡ Review Ingestion & Classification Manager</h3>", unsafe_allow_html=True)
    st.markdown(f"<p style='margin:4px 0 0 0; font-size:0.85rem; color:#a1a1aa;'>The pipeline has identified <b>{unprocessed_count}</b> unprocessed reviews in the database queue. Use the controls to fetch new feedback or analyze the queue.</p>", unsafe_allow_html=True)
    
    # Toggle for Demo Ingest Mode (adds mock reviews if live scrape yields no new reviews)
    demo_mode = st.checkbox("Enable Demo Ingestion Mode (injects fresh reviews if live stores yield no new data)", value=True, help="Guarantees new reviews are added on every click for testing purposes.")
    
    # Display active model status
    api_status = "<span style='color: #10b981; font-weight: 500; font-size: 0.78rem;'>● Groq AI Model Active (Llama 3.3)</span>" if GROQ_API_KEY else "<span style='color: #f59e0b; font-weight: 500; font-size: 0.78rem;'>● Local Heuristics Fallback Active (Groq API Key not configured)</span>"
    st.markdown(f"<div style='margin-top: 6px;'>{api_status}</div>", unsafe_allow_html=True)

with col_btn:
    if st.button("Start Classification Run", use_container_width=True):
        if unprocessed_count == 0:
            st.warning("All records already classified.")
        else:
            st.session_state.run_classification = True
            
    if st.button("⚡ Fetch Latest Reviews", use_container_width=True):
        st.session_state.run_scraping = True
        
    if st.button("⚙️ Ingestion Settings", use_container_width=True):
        st.session_state.show_settings = True

# Run classification or scraping outside of columns at full width
if st.session_state.run_classification:
    run_ai_classification_in_ui()
    st.session_state.run_classification = False
    st.rerun()

if st.session_state.run_scraping:
    run_scraping_in_ui(demo_mode)
    st.session_state.run_scraping = False
    st.rerun()

st.markdown("<hr style='border: 0; border-top: 1px solid #27272a; margin: 15px 0 25px 0;'>", unsafe_allow_html=True)

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

if not full_df.empty:
    pos_df = full_df[full_df["Theme"].isin(["Accurate Recommendations", "Great UI/UX", "Smart Curation", "Positive"])]
    total_pos = len(pos_df)
    if not pos_df.empty:
        specific_pos = pos_df[pos_df["Theme"] != "Positive"]
        if not specific_pos.empty:
            top_positive_theme = specific_pos["Theme"].value_counts().index[0]
        else:
            top_positive_theme = pos_df["Theme"].value_counts().index[0]
    else:
        top_positive_theme = "None"
else:
    total_pos = 0
    top_positive_theme = "N/A"

# KPIs Grid
col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)

with col_kpi1:
    st.metric("Total Defects Ingested", total_defects, help="Total number of active product pain points/complaints")
with col_kpi2:
    st.metric("Frustration Rate", frustration_rate, help="Percentage of reviews flagged as Highly Frustrated")
with col_kpi3:
    st.metric("Primary Blocker Theme", top_defect, help="Top defect category blocking user engagement")
with col_kpi4:
    st.metric("Top Positive Feature", top_positive_theme, help=f"Total positive reviews: {total_pos} (kept in Excel for further exploration)")

# Bind datasets directly (filtering is handled in the exported Excel spreadsheet)
filtered_full_df = full_df

# Separate the dataset into negative defects and positive features for charts
pos_themes = ["Accurate Recommendations", "Great UI/UX", "Smart Curation", "Positive"]
filtered_df = filtered_full_df[~filtered_full_df["Theme"].isin(pos_themes)] if not filtered_full_df.empty else pd.DataFrame()
filtered_pos_df = filtered_full_df[filtered_full_df["Theme"].isin(pos_themes)] if not filtered_full_df.empty else pd.DataFrame()
 
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
 
st.markdown("<hr style='border: 0; border-top: 1px solid #27272a; margin: 25px 0;'>", unsafe_allow_html=True)

# Positive Diagnostics Section
st.subheader("💚 Customer Curation & Positive Feature Diagnostics")
col_pos_chart1, col_pos_chart2 = st.columns(2)

with col_pos_chart1:
    st.markdown("**Positive Features Distribution**")
    if not filtered_pos_df.empty:
        pos_theme_counts = filtered_pos_df["Theme"].value_counts().reset_index()
        pos_theme_counts.columns = ["Theme", "Count"]
        st.bar_chart(pos_theme_counts.set_index("Theme"))
    else:
        st.info("No positive records match the active filters.")

with col_pos_chart2:
    st.markdown("**Satisfied User Cohorts**")
    if not filtered_pos_df.empty:
        pos_cohort_counts = filtered_pos_df["User Type"].value_counts().reset_index()
        pos_cohort_counts.columns = ["Cohort", "Count"]
        st.bar_chart(pos_cohort_counts.set_index("Cohort"))
    else:
        st.info("No positive records match the active filters.")

st.markdown("<br>", unsafe_allow_html=True)

# Export & Reporting Container
st.subheader("📥 Export & Reporting")
with st.container(border=True):
    col_down_text, col_down_btn = st.columns([3, 1])
    with col_down_text:
        st.markdown("<p style='margin:0; font-size:0.9rem; color:#a1a1aa;'>Generate a comprehensive Microsoft Excel report. The report automatically includes all raw reviews, sentiment tags, user cohort mappings, and a <b>PM Pivot Summary</b> cross-tabulation sheet (including positive feedback).</p>", unsafe_allow_html=True)
    with col_down_btn:
        # Formulate export DataFrame based on active Filter Matrix selections
        export_df = filtered_full_df

        if not export_df.empty:
            excel_binary = generate_excel_bytes(export_df)
            st.download_button(
                label="💾 DOWNLOAD EXCEL REPORT",
                data=excel_binary,
                file_name=f"Spotify_Growth_Metrics_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.button("💾 DOWNLOAD EXCEL REPORT", disabled=True, use_container_width=True)

st.markdown("<br>", unsafe_allow_html=True)
 
# Data Table Grid
st.subheader("📋 Classified Reviews Feed")
if not filtered_full_df.empty:
    st.dataframe(
        filtered_full_df[["Timestamp", "Source", "Theme", "Sentiment", "User Type", "Root Cause", "Text"]],
        use_container_width=True,
        column_config={
            "Timestamp": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            "Text": st.column_config.TextColumn(width="large")
        }
    )
else:
    st.warning("No records match the active filter configurations.")
