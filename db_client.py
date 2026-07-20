import os
import json
import sqlite3
import hashlib
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load env variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

_USE_LOCAL_SQLITE = False
_sqlite_conn = None

def init_db():
    global _USE_LOCAL_SQLITE, _sqlite_conn
    
    # Check if we should force SQLite (e.g. no internet/credentials)
    if not SUPABASE_URL or not SUPABASE_KEY or "your-" in SUPABASE_URL:
        print("[DB Client] Supabase credentials missing. Activating Local SQLite mode.")
        _USE_LOCAL_SQLITE = True
    else:
        # Check connectivity by testing Supabase import and initializing
        try:
            from supabase import create_client
            # Verify basic DNS/connection with a quick ping logic, if it fails, fall back to SQLite
            # We will catch any getaddrinfo/connection exceptions on first query
            create_client(SUPABASE_URL, SUPABASE_KEY)
        except Exception as e:
            print(f"[DB Client] Supabase connection failed: {e}. Activating Local SQLite mode.")
            _USE_LOCAL_SQLITE = True
            
    if _USE_LOCAL_SQLITE:
        db_path = "local_storage.db"
        print(f"[DB Client] Initializing SQLite local database: {db_path}")
        _sqlite_conn = sqlite3.connect(db_path, check_same_thread=False)
        _sqlite_conn.row_factory = sqlite3.Row
        
        # Create SQLite schema matching Postgres
        cursor = _sqlite_conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_feedback (
                review_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                text TEXT NOT NULL,
                app_version_approx TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_analytics (
                review_id TEXT PRIMARY KEY,
                theme TEXT NOT NULL,
                sentiment TEXT NOT NULL,
                user_type TEXT NOT NULL,
                root_cause TEXT NOT NULL,
                confidence_score INTEGER,
                audited INTEGER DEFAULT 0,
                audit_theme TEXT,
                audit_sentiment TEXT,
                audit_user_type TEXT,
                spot_checked INTEGER DEFAULT 0,
                spot_check_valid INTEGER,
                analyzed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(review_id) REFERENCES raw_feedback(review_id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS filter_keywords (
                keyword TEXT PRIMARY KEY,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                phase TEXT NOT NULL,
                status TEXT NOT NULL,
                records_processed INTEGER DEFAULT 0,
                validation_results TEXT,
                metadata TEXT
            )
        """)
        
        # Seed keywords
        initial_keywords = [
            'category', 'explore', 'recommend', 'reorder', 'never tried',
            'search', 'browse', 'out of stock', 'substitute', 'finding',
            'navigation', 'layout', 'fresh', 'vegetables', 'groceries',
            'fruits', 'delivery', 'slop', 'clutter', 'widget', 'item'
        ]
        for kw in initial_keywords:
            cursor.execute("INSERT OR IGNORE INTO filter_keywords (keyword) VALUES (?)", (kw,))
        _sqlite_conn.commit()

# Run initialization
init_db()

def get_supabase_client():
    if _USE_LOCAL_SQLITE:
        return None
    try:
        from supabase import create_client
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        return None

# --- Ingestion operations ---

def insert_raw_feedback(records):
    """Upsert raw feedback records."""
    global _USE_LOCAL_SQLITE
    if _USE_LOCAL_SQLITE:
        cursor = _sqlite_conn.cursor()
        for r in records:
            cursor.execute("""
                INSERT OR REPLACE INTO raw_feedback 
                (review_id, source, timestamp, text, app_version_approx)
                VALUES (?, ?, ?, ?, ?)
            """, (r["review_id"], r["source"], r["timestamp"], r["text"], r.get("app_version_approx")))
        _sqlite_conn.commit()
        return len(records)
    else:
        client = get_supabase_client()
        try:
            res = client.table("raw_feedback").upsert(records, on_conflict="review_id").execute()
            return len(res.data) if res.data else len(records)
        except Exception as e:
            print(f"[DB Client] Supabase error in insert_raw_feedback: {e}. Retrying locally...")
            # Toggle SQLite fallback on the fly
            _USE_LOCAL_SQLITE = True
            init_db()
            return insert_raw_feedback(records)

def fetch_unprocessed_feedback(limit=900):
    """Retrieve feedback records that do not have associated analytics classifications."""
    global _USE_LOCAL_SQLITE
    if _USE_LOCAL_SQLITE:
        cursor = _sqlite_conn.cursor()
        cursor.execute("""
            SELECT r.review_id, r.text 
            FROM raw_feedback r
            LEFT JOIN ai_analytics a ON r.review_id = a.review_id
            WHERE a.review_id IS NULL
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
    else:
        client = get_supabase_client()
        try:
            res = client.table("unprocessed_feedback").select("review_id, text").limit(limit).execute()
            return res.data if res.data else []
        except Exception as e:
            print(f"[DB Client] Supabase error: {e}. Falling back to SQLite.")
            _USE_LOCAL_SQLITE = True
            init_db()
            return fetch_unprocessed_feedback(limit)

# --- Keywords operations ---

def fetch_keywords():
    """Retrieve active keywords for scraper filters."""
    global _USE_LOCAL_SQLITE
    if _USE_LOCAL_SQLITE:
        cursor = _sqlite_conn.cursor()
        cursor.execute("SELECT keyword FROM filter_keywords")
        return [row["keyword"] for row in cursor.fetchall()]
    else:
        client = get_supabase_client()
        try:
            res = client.table("filter_keywords").select("keyword").execute()
            return [row["keyword"] for row in res.data] if res.data else []
        except Exception as e:
            print(f"[DB Client] Supabase error in fetch_keywords: {e}. Falling back to SQLite.")
            _USE_LOCAL_SQLITE = True
            init_db()
            return fetch_keywords()

def insert_keywords(keywords):
    """Set the filter keywords list (clearing previous and inserting new)."""
    global _USE_LOCAL_SQLITE
    if _USE_LOCAL_SQLITE:
        cursor = _sqlite_conn.cursor()
        cursor.execute("DELETE FROM filter_keywords")
        for kw in keywords:
            cursor.execute("INSERT OR IGNORE INTO filter_keywords (keyword) VALUES (?)", (kw,))
        _sqlite_conn.commit()
    else:
        client = get_supabase_client()
        try:
            client.table("filter_keywords").delete().neq("keyword", "placeholder").execute()
            records = [{"keyword": kw} for kw in keywords]
            if records:
                client.table("filter_keywords").insert(records).execute()
        except Exception as e:
            print(f"[DB Client] Supabase error in insert_keywords: {e}. Falling back to SQLite.")
            _USE_LOCAL_SQLITE = True
            init_db()
            insert_keywords(keywords)

# --- Analytics Operations ---

def insert_ai_analytics(records):
    """Upsert classification results into ai_analytics."""
    global _USE_LOCAL_SQLITE
    if _USE_LOCAL_SQLITE:
        cursor = _sqlite_conn.cursor()
        for r in records:
            cursor.execute("""
                INSERT OR REPLACE INTO ai_analytics 
                (review_id, theme, sentiment, user_type, root_cause, confidence_score, audited, audit_theme, audit_sentiment, audit_user_type, spot_checked, spot_check_valid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r["review_id"], r["theme"], r["sentiment"], r["user_type"], r["root_cause"], r.get("confidence_score"),
                1 if r.get("audited") else 0, r.get("audit_theme"), r.get("audit_sentiment"), r.get("audit_user_type"),
                1 if r.get("spot_checked") else 0, 1 if r.get("spot_check_valid") else (0 if r.get("spot_check_valid") == False else None)
            ))
        _sqlite_conn.commit()
        return len(records)
    else:
        client = get_supabase_client()
        try:
            res = client.table("ai_analytics").upsert(records, on_conflict="review_id").execute()
            return len(res.data) if res.data else len(records)
        except Exception as e:
            print(f"[DB Client] Supabase error in insert_ai_analytics: {e}. Falling back to SQLite.")
            _USE_LOCAL_SQLITE = True
            init_db()
            return insert_ai_analytics(records)

# --- Audit Runs ---

def log_pipeline_run(phase, status, records_processed=0, validation_results=None, metadata=None):
    """Log execution status and audit metrics."""
    global _USE_LOCAL_SQLITE
    val_json = json.dumps(validation_results) if validation_results else None
    meta_json = json.dumps(metadata) if metadata else None
    
    if _USE_LOCAL_SQLITE:
        cursor = _sqlite_conn.cursor()
        cursor.execute("""
            INSERT INTO pipeline_runs (phase, status, records_processed, validation_results, metadata)
            VALUES (?, ?, ?, ?, ?)
        """, (phase, status, records_processed, val_json, meta_json))
        _sqlite_conn.commit()
    else:
        client = get_supabase_client()
        try:
            record = {
                "phase": phase,
                "status": status,
                "records_processed": records_processed,
                "validation_results": validation_results,
                "metadata": metadata
            }
            client.table("pipeline_runs").insert(record).execute()
        except Exception as e:
            print(f"[DB Client] Supabase error in log_pipeline_run: {e}. Falling back to SQLite.")
            _USE_LOCAL_SQLITE = True
            init_db()
            log_pipeline_run(phase, status, records_processed, validation_results, metadata)

# --- Fetch Dashboard Data ---

def fetch_analyzed_data():
    """Fetch raw feedback combined with their analytical dimensions."""
    global _USE_LOCAL_SQLITE
    if _USE_LOCAL_SQLITE:
        cursor = _sqlite_conn.cursor()
        cursor.execute("""
            SELECT 
                r.review_id as "Review ID", 
                r.source as "Source", 
                r.timestamp as "Timestamp", 
                r.text as "Text", 
                r.app_version_approx as "App Version",
                a.theme as "Theme", 
                a.sentiment as "Sentiment", 
                a.user_type as "User Type", 
                a.root_cause as "Root Cause",
                a.confidence_score as "Confidence Score",
                a.audited as "Audited",
                a.audit_theme as "Audit Theme",
                a.audit_sentiment as "Audit Sentiment",
                a.audit_user_type as "Audit User Type",
                a.spot_checked as "Spot Checked",
                a.spot_check_valid as "Spot Check Valid",
                a.analyzed_at as "Analyzed At"
            FROM raw_feedback r
            JOIN ai_analytics a ON r.review_id = a.review_id
            ORDER BY r.timestamp DESC
        """)
        import pandas as pd
        rows = [dict(row) for row in cursor.fetchall()]
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)
    else:
        client = get_supabase_client()
        try:
            response = client.table("raw_feedback").select(
                "review_id, source, timestamp, text, app_version_approx, ai_analytics(theme, sentiment, user_type, root_cause, confidence_score, audited, audit_theme, audit_sentiment, audit_user_type, spot_checked, spot_check_valid, analyzed_at)"
            ).order("timestamp", desc=True).execute()
            
            data = response.data
            if not data:
                import pandas as pd
                return pd.DataFrame()
                
            rows = []
            for item in data:
                analytics = item.get("ai_analytics")
                # Handle cases where postgrest returns a list or dict
                if isinstance(analytics, list) and len(analytics) > 0:
                    analytics = analytics[0]
                
                if analytics and isinstance(analytics, dict):
                    rows.append({
                        "Review ID": item["review_id"],
                        "Source": item["source"],
                        "Timestamp": item["timestamp"],
                        "Text": item["text"],
                        "App Version": item.get("app_version_approx", "N/A"),
                        "Theme": analytics["theme"],
                        "Sentiment": analytics["sentiment"],
                        "User Type": analytics["user_type"],
                        "Root Cause": analytics["root_cause"],
                        "Confidence Score": analytics.get("confidence_score", 0),
                        "Audited": analytics.get("audited", False),
                        "Audit Theme": analytics.get("audit_theme"),
                        "Audit Sentiment": analytics.get("audit_sentiment"),
                        "Audit User Type": analytics.get("audit_user_type"),
                        "Spot Checked": analytics.get("spot_checked", False),
                        "Spot Check Valid": analytics.get("spot_check_valid"),
                        "Analyzed At": analytics["analyzed_at"]
                    })
            
            import pandas as pd
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame(rows)
            return df
        except Exception as e:
            print(f"[DB Client] Supabase error in fetch_analyzed_data: {e}. Falling back to SQLite.")
            _USE_LOCAL_SQLITE = True
            init_db()
            return fetch_analyzed_data()

def update_spot_check(review_id, is_valid):
    """Save user manual spot-check result."""
    global _USE_LOCAL_SQLITE
    if _USE_LOCAL_SQLITE:
        cursor = _sqlite_conn.cursor()
        cursor.execute("""
            UPDATE ai_analytics 
            SET spot_checked = 1, spot_check_valid = ?
            WHERE review_id = ?
        """, (1 if is_valid else 0, review_id))
        _sqlite_conn.commit()
    else:
        client = get_supabase_client()
        try:
            client.table("ai_analytics").update({
                "spot_checked": True,
                "spot_check_valid": is_valid
            }).eq("review_id", review_id).execute()
        except Exception as e:
            print(f"[DB Client] Supabase error in update_spot_check: {e}. Falling back to SQLite.")
            _USE_LOCAL_SQLITE = True
            init_db()
            update_spot_check(review_id, is_valid)

def fetch_pipeline_runs(limit=10):
    """Retrieve run audit logs."""
    global _USE_LOCAL_SQLITE
    if _USE_LOCAL_SQLITE:
        cursor = _sqlite_conn.cursor()
        cursor.execute("SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]
    else:
        client = get_supabase_client()
        try:
            res = client.table("pipeline_runs").select("*").order("id", desc=True).limit(limit).execute()
            return res.data if res.data else []
        except Exception as e:
            print(f"[DB Client] Supabase error in fetch_pipeline_runs: {e}. Falling back to SQLite.")
            _USE_LOCAL_SQLITE = True
            init_db()
            return fetch_pipeline_runs(limit)
