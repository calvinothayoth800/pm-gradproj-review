import os
import json
import time
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load env variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            SUPABASE_URL = st.secrets.get("SUPABASE_URL", SUPABASE_URL)
            SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", SUPABASE_KEY)
    except Exception:
        pass

_USE_LOCAL_SQLITE = False

def init_db():
    """No-op for strict Supabase mode."""
    pass

def get_supabase_client():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def retry_supabase_call(fn, retries=3, delay=1.0):
    """Retry a Supabase API call up to n times for transient network glitches."""
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            if i == retries - 1:
                raise e
            time.sleep(delay)

# --- Ingestion operations ---

def insert_raw_feedback(records):
    """Upsert raw feedback records."""
    client = get_supabase_client()
    def call():
        res = client.table("raw_feedback").upsert(records, on_conflict="review_id").execute()
        return len(res.data) if res.data else len(records)
    return retry_supabase_call(call)

def fetch_unprocessed_feedback(limit=900):
    """Retrieve feedback records that do not have associated analytics classifications."""
    client = get_supabase_client()
    def call():
        res = client.table("unprocessed_feedback").select("review_id, text").limit(limit).execute()
        return res.data if res.data else []
    return retry_supabase_call(call)

# --- Keywords operations ---

def fetch_keywords():
    """Retrieve active keywords for scraper filters."""
    client = get_supabase_client()
    def call():
        res = client.table("filter_keywords").select("keyword").execute()
        return [row["keyword"] for row in res.data] if res.data else []
    return retry_supabase_call(call)

def insert_keywords(keywords):
    """Set the filter keywords list (clearing previous and inserting new)."""
    client = get_supabase_client()
    def call():
        client.table("filter_keywords").delete().neq("keyword", "placeholder").execute()
        records = [{"keyword": kw} for kw in keywords]
        if records:
            client.table("filter_keywords").insert(records).execute()
    retry_supabase_call(call)

# --- Analytics Operations ---

def insert_ai_analytics(records):
    """Upsert classification results into ai_analytics."""
    client = get_supabase_client()
    def call():
        res = client.table("ai_analytics").upsert(records, on_conflict="review_id").execute()
        return len(res.data) if res.data else len(records)
    return retry_supabase_call(call)

# --- Audit Runs ---

def log_pipeline_run(phase, status, records_processed=0, validation_results=None, metadata=None):
    """Log execution status and audit metrics."""
    client = get_supabase_client()
    def call():
        record = {
            "phase": phase,
            "status": status,
            "records_processed": records_processed,
            "validation_results": validation_results,
            "metadata": metadata
        }
        client.table("pipeline_runs").insert(record).execute()
    try:
        retry_supabase_call(call)
    except Exception as e:
        print(f"[DB Client] Failed to log pipeline run to Supabase: {e}")

# --- Fetch Dashboard Data ---

def fetch_analyzed_data():
    """Fetch raw feedback combined with their analytical dimensions."""
    client = get_supabase_client()
    def call():
        response = client.table("raw_feedback").select(
            "review_id, source, timestamp, text, app_version_approx, ai_analytics(theme, sentiment, user_type, root_cause, confidence_score, audited, audit_theme, audit_sentiment, audit_user_type, spot_checked, spot_check_valid, analyzed_at)"
        ).order("timestamp", desc=True).execute()
        return response.data
    
    data = retry_supabase_call(call)
    if not data:
        import pandas as pd
        return pd.DataFrame()
        
    rows = []
    for item in data:
        analytics = item.get("ai_analytics")
        if isinstance(analytics, list) and len(analytics) > 0:
            analytics = analytics[0]
        
        if analytics and isinstance(analytics, dict):
            rows.append({
                "Review ID": item["review_id"],
                "Source": item["source"],
                "Timestamp": item["timestamp"],
                "Text": item["text"],
                "App Version": item.get("app_version_approx", "N/A"),
                "Theme": analytics.get("theme", "N/A"),
                "Sentiment": analytics.get("sentiment", "N/A"),
                "User Type": analytics.get("user_type", "N/A"),
                "Root Cause": analytics.get("root_cause", "N/A"),
                "Confidence Score": analytics.get("confidence_score", 0),
                "Audited": analytics.get("audited", False),
                "Audit Theme": analytics.get("audit_theme"),
                "Audit Sentiment": analytics.get("audit_sentiment"),
                "Audit User Type": analytics.get("audit_user_type"),
                "Spot Checked": analytics.get("spot_checked", False),
                "Spot Check Valid": analytics.get("spot_check_valid"),
                "Analyzed At": analytics.get("analyzed_at", "N/A")
            })
    
    import pandas as pd
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df

def update_spot_check(review_id, is_valid):
    """Save user manual spot-check result."""
    client = get_supabase_client()
    def call():
        client.table("ai_analytics").update({
            "spot_checked": True,
            "spot_check_valid": is_valid
        }).eq("review_id", review_id).execute()
    retry_supabase_call(call)

def fetch_pipeline_runs(limit=10):
    """Retrieve run audit logs."""
    client = get_supabase_client()
    def call():
        res = client.table("pipeline_runs").select("*").order("id", desc=True).limit(limit).execute()
        return res.data if res.data else []
    return retry_supabase_call(call)

def get_db_counts():
    """Get count of unclassified and classified reviews."""
    client = get_supabase_client()
    def call():
        res_unclass = client.table("unprocessed_feedback").select("review_id", count='exact').limit(1).execute()
        unclassified = res_unclass.count if res_unclass.count is not None else 0
        
        res_class = client.table("ai_analytics").select("review_id", count="exact").limit(1).execute()
        classified = res_class.count if res_class.count is not None else 0
        
        return {"unclassified": unclassified, "classified": classified}
    return retry_supabase_call(call)
