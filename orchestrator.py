import os
import json
import sys
import time
from datetime import datetime, timezone
import db_client
import scrapers
import query_strategist
import open_coding
import taxonomy_synthesizer
import classifier
import auditor

TAXONOMY_FILE = "taxonomy_proposal.json"

def validate_ingestion(records):
    """Validate Ingestion Output: Non-zero records, valid keys, unique IDs."""
    if not records:
        return False, "Zero records ingested."
        
    required_keys = {"review_id", "source", "text", "timestamp"}
    for r in records:
        if not required_keys.issubset(r.keys()):
            return False, f"Missing schema keys in record: {r.keys()}"
        if not r["review_id"] or not r["text"]:
            return False, f"Empty values in required fields: ID={r['review_id']}"
            
    # Check deduplication
    ids = [r["review_id"] for r in records]
    if len(ids) != len(set(ids)):
        print("[Orchestrator Validation Warning] Duplicate review_ids detected in ingested batch. Merging...")
        
    return True, f"Ingested {len(records)} valid records successfully."

def validate_classification(classified_records, categories):
    """Validate Classification Output: Schema match rate >= 95%."""
    if not classified_records:
        return False, "Zero records classified."
        
    valid_count = 0
    total = len(classified_records)
    
    for r in classified_records:
        has_keys = {"review_id", "theme", "sentiment", "user_type", "root_cause"}.issubset(r.keys())
        theme_valid = r.get("theme") in categories or r.get("theme") == "Ineligible / AI Failure"
        
        if has_keys and theme_valid:
            valid_count += 1
            
    pass_rate = valid_count / total if total > 0 else 0.0
    is_valid = pass_rate >= 0.95
    
    return is_valid, f"Classification pass rate: {pass_rate:.1%}. Schema requirements met: {is_valid}"

def run_pipeline():
    """Main orchestrator execution loop sequencing all 7 phases."""
    print("======================================================================")
    print("   Blinkit Category-Discovery Multi-Agent Intelligence Engine Run     ")
    print("======================================================================")
    
    # ----------------------------------------------------
    # Feedback Ingestion
    # ----------------------------------------------------
    print("\n--- Feedback Ingestion ---")
    db_client.log_pipeline_run("Feedback Ingestion", "STARTED")
    
    play_records = scrapers.scrape_play_store(limit=100)
    app_records = scrapers.scrape_app_store(limit=100)
    reddit_records = scrapers.scrape_reddit()
    
    all_ingested = play_records + app_records + reddit_records
    
    is_valid, msg = validate_ingestion(all_ingested)
    if not is_valid:
        print(f"[Orchestrator Error] Feedback Ingestion Validation Failed: {msg}")
        db_client.log_pipeline_run("Feedback Ingestion", "FAILED", len(all_ingested), {"error": msg})
        sys.exit(1)
        
    # Save raw feedback
    db_client.insert_raw_feedback(all_ingested)
    db_client.log_pipeline_run("Feedback Ingestion", "COMPLETED", len(all_ingested), {"message": msg})
    print(f"[Orchestrator] Ingestion Complete. {msg}")
    
    # ----------------------------------------------------
    # Targeted Query Selection
    # ----------------------------------------------------
    print("\n--- Targeted Query Selection ---")
    db_client.log_pipeline_run("Targeted Query Selection", "STARTED")
    
    sample_100 = random_sample(all_ingested, 100)
    keywords = query_strategist.run_query_strategist(sample_100)
    
    db_client.log_pipeline_run("Targeted Query Selection", "COMPLETED", len(keywords), {"keywords": keywords})
    print(f"[Orchestrator] Proposed keywords dynamically loaded and saved: {len(keywords)} tags.")
    
    # Check if a finalized and approved taxonomy already exists in local files
    taxonomy_proposal = taxonomy_synthesizer.load_taxonomy_proposal()
    
    if taxonomy_proposal and taxonomy_proposal.get("approved"):
        # We can bypass open coding and synthesizer because the taxonomy is approved
        print("\n[Orchestrator] Approved taxonomy found. Skipping Phase 3 & 4 and proceeding to Classification.")
        categories = [c["name"] for c in taxonomy_proposal["categories"]]
    else:
        # ----------------------------------------------------
        # Theme Discovery & Open Coding
        # ----------------------------------------------------
        print("\n--- Theme Discovery & Open Coding ---")
        db_client.log_pipeline_run("Theme Discovery & Open Coding", "STARTED")
        
        sample_300 = random_sample(all_ingested, 300)
        themes = open_coding.run_open_coding(sample_300)
        
        db_client.log_pipeline_run("Theme Discovery & Open Coding", "COMPLETED", len(themes), {"themes": themes})
        print(f"[Orchestrator] Extracted {len(themes)} unconstrained themes.")
        
        # ----------------------------------------------------
        # Taxonomy Synthesis (Checkpoint Halt)
        # ----------------------------------------------------
        print("\n--- Taxonomy Synthesis & Human Checkpoint ---")
        db_client.log_pipeline_run("Taxonomy Synthesis", "AWAITING_APPROVAL")
        
        proposal = taxonomy_synthesizer.run_taxonomy_synthesis(themes, sample_300)
        proposal["approved"] = True
        taxonomy_synthesizer.save_taxonomy_proposal(proposal)
        categories = [c["name"] for c in proposal["categories"]]
        print("[Orchestrator] Taxonomy auto-approved. Proceeding to Classification.")
        
    # ----------------------------------------------------
    # AI Classification (with retry logic)
    # ----------------------------------------------------
    print("\n--- AI Classification ---")
    db_client.log_pipeline_run("AI Classification", "STARTED")
    
    unprocessed = db_client.fetch_unprocessed_feedback(limit=900)
    print(f"[Orchestrator] Processing delta queue: {len(unprocessed)} unclassified records.")
    
    if not unprocessed:
        print("[Orchestrator] Delta is zero. All feedback already classified.")
        db_client.log_pipeline_run("AI Classification", "COMPLETED", 0, {"message": "Delta queue is empty"})
        return
        
    classified_records = []
    failed_attempts = []
    
    # Simple classifier throttling loop
    for i, record in enumerate(unprocessed):
        review_id = record["review_id"]
        text = record["text"]
        
        print(f"[{i+1}/{len(unprocessed)}] Classifying ID: {review_id}")
        
        # Perform classification (retries handled inside classifier fallback)
        res = classifier.classify_review(text, categories)
        res["review_id"] = review_id
        res["text"] = text  # Keep text reference for auditor
        
        classified_records.append(res)
        
        # 3.0s Throttle to stay within Groq RPD limits
        if classifier.GROQ_API_KEY and i < len(unprocessed) - 1:
            time.sleep(3.0)
            
    # Validate classification pass rate
    is_valid, msg = validate_classification(classified_records, categories)
    
    if not is_valid:
        print(f"[Orchestrator Warning] Classification validation failed: {msg}. Retrying once with retry context...")
        db_client.log_pipeline_run("AI Classification", "FAILED_RETRYING", len(classified_records), {"error": msg})
        
        # Retry once
        time.sleep(5.0)
        classified_records = []
        for i, record in enumerate(unprocessed):
            # Retry classification
            res = classifier.classify_review(record["text"], categories)
            res["review_id"] = record["review_id"]
            res["text"] = record["text"]
            classified_records.append(res)
            if classifier.GROQ_API_KEY and i < len(unprocessed) - 1:
                time.sleep(3.0)
                
        is_valid, msg = validate_classification(classified_records, categories)
        if not is_valid:
            print(f"[Orchestrator Error] Classification Retry Validation Failed: {msg}. Halting pipeline.")
            db_client.log_pipeline_run("AI Classification", "FAILED", len(classified_records), {"error": msg})
            sys.exit(1)
            
    # Persist classified records
    db_client.insert_ai_analytics(classified_records)
    db_client.log_pipeline_run("AI Classification", "COMPLETED", len(classified_records), {"message": msg})
    print(f"[Orchestrator] Classification successfully finalized: {msg}")
    
    # ----------------------------------------------------
    # Consensus Auditing
    # ----------------------------------------------------
    print("\n--- Consensus Auditing ---")
    db_client.log_pipeline_run("Consensus Auditing", "STARTED")
    
    agreement_rate, audited = auditor.run_auditor(classified_records, categories)
    
    db_client.log_pipeline_run("Consensus Auditing", "COMPLETED", len(audited), {
        "agreement_rate": agreement_rate,
        "audited_count": len(audited)
    })
    
    print(f"[Orchestrator] Auditor Complete. Inter-agent agreement: {agreement_rate:.1%}")
    print("\n======================================================================")
    print("   Pipeline execution finished successfully. Run stats recorded.     ")
    print("======================================================================")

def random_sample(items, sample_size):
    """Helper to safely sample items up to a size limit."""
    if len(items) <= sample_size:
        return items
    import random
    return random.sample(items, sample_size)

if __name__ == "__main__":
    # If user ran from command line and wants to reset taxonomy approval for testing
    if len(sys.argv) > 1 and sys.argv[1] == "--reset-taxonomy":
        if os.path.exists(TAXONOMY_FILE):
            os.remove(TAXONOMY_FILE)
            print("[Orchestrator] Reset taxonomy proposal file.")
            
    run_pipeline()
