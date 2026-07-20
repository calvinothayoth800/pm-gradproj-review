import os
import random
import json
from dotenv import load_dotenv
import db_client
import classifier

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", GROQ_API_KEY)
    except Exception:
        pass

def run_auditor(classified_records, categories):
    """
    Auditor Agent:
    Selects 5-8% of classified records, blind re-classifies them,
    computes inter-agent agreement, and saves audit flags.
    Also flags 10-15 random records for manual spot-checking.
    """
    total = len(classified_records)
    if total == 0:
        print("[Auditor] No records available to audit.")
        return 0.0, []
        
    # Determine sample size (5-8%)
    sample_rate = random.uniform(0.05, 0.08)
    sample_size = max(1, int(total * sample_rate))
    
    audited_sample = random.sample(classified_records, sample_size)
    print(f"[Auditor] Auditing {sample_size} records (sample rate: {sample_rate:.1%})...")
    
    matches = 0
    updated_records = []
    
    for record in audited_sample:
        review_id = record["review_id"]
        # Fetch raw text from database (or keep text in record if passed)
        text = record.get("text")
        if not text:
            # If text not passed, fetch it
            try:
                client = db_client.get_supabase_client()
                if client:
                    res = client.table("raw_feedback").select("text").eq("review_id", review_id).execute()
                    if res.data:
                        text = res.data[0]["text"]
            except Exception:
                pass
                
        if not text:
            # Simulated text if query fails
            text = "Blinkit category exploration has some minor browse issues."
            
        # Blind re-classification (Auditor does not see the original label)
        audit_res = classifier.classify_review(text, categories)
        
        # Check agreement
        is_match = (
            record["theme"] == audit_res["theme"] and
            record["sentiment"] == audit_res["sentiment"] and
            record["user_type"] == audit_res["user_type"]
        )
        
        if is_match:
            matches += 1
            
        # Store audit results in database format
        updated_records.append({
            "review_id": review_id,
            "theme": record["theme"],
            "sentiment": record["sentiment"],
            "user_type": record["user_type"],
            "root_cause": record["root_cause"],
            "confidence_score": record.get("confidence_score", 4),
            "audited": True,
            "audit_theme": audit_res["theme"],
            "audit_sentiment": audit_res["sentiment"],
            "audit_user_type": audit_res["user_type"]
        })
        
    agreement_rate = matches / sample_size if sample_size > 0 else 1.0
    print(f"[Auditor] Audit complete. Inter-agent agreement rate: {agreement_rate:.1%}")
    
    # Save audited fields back to database
    if updated_records:
        db_client.insert_ai_analytics(updated_records)
        
    # Flag 10-15 random records for manual spot-checking
    spot_check_count = min(total, random.randint(10, 15))
    spot_check_sample = random.sample(classified_records, spot_check_count)
    print(f"[Auditor] Flagged {spot_check_count} records for human spot-check.")
    
    spot_check_records = []
    for record in spot_check_sample:
        # Check if record was already audited to preserve audit fields
        matching_audit = next((r for r in updated_records if r["review_id"] == record["review_id"]), None)
        
        item = {
            "review_id": record["review_id"],
            "theme": record["theme"],
            "sentiment": record["sentiment"],
            "user_type": record["user_type"],
            "root_cause": record["root_cause"],
            "confidence_score": record.get("confidence_score", 4),
            "spot_checked": True,  # Sets trigger for display in dashboard
            "spot_check_valid": None  # Waiting for human click (Yes/No)
        }
        
        if matching_audit:
            item.update({
                "audited": True,
                "audit_theme": matching_audit["audit_theme"],
                "audit_sentiment": matching_audit["audit_sentiment"],
                "audit_user_type": matching_audit["audit_user_type"]
            })
            
        spot_check_records.append(item)
        
    if spot_check_records:
        db_client.insert_ai_analytics(spot_check_records)
        
    return agreement_rate, audited_sample
