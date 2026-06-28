#!/usr/bin/env python
"""
AI-Native Review Discovery Engine - Core Pipeline (pipeline.py)
Orchestrates multi-source scraping, delta evaluation, LLM classification, and Supabase upserts.
"""

import os
import re
import json
import time
import hashlib
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Rate limit configurations
RPM_DELAY = 3.0  # 3 seconds delay = 20 Requests Per Minute
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "900"))  # Cap processing at 900 records in a single run

# Ingestion filter keywords
KEYWORDS = ["discovery", "recommendation", "smart shuffle", "shuffle", "algorithm", "same songs", "echo chamber", "loop"]

# Allowed enums for validation
THEME_ENUM = [
    "Echo Chamber", "Smart Shuffle Failure", "Niche Genre Blending", "UI/UX Clutter",
    "Accurate Recommendations", "Great UI/UX", "Smart Curation", "Positive"
]
SENTIMENT_ENUM = ["Negative", "Highly Frustrated", "Disappointed", "Positive"]
USER_TYPE_ENUM = ["Power User", "Casual Listener", "Audiophile", "Playlist Curator"]

def compute_md5(source, platform_id):
    """Compute a deterministic MD5 hash for deduplication."""
    hasher = hashlib.md5()
    hasher.update(f"{source}:{platform_id}".encode("utf-8"))
    return hasher.hexdigest()

def clean_text(text):
    """Clean string of formatting anomalies and cap at 800 characters."""
    if not text:
        return ""
    # Strip markdown, HTML, and extra whitespace
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text[:800].strip()

# --- Scraping Ingestion Modules ---

def scrape_app_store(app_id="324684580", source="App Store"):
    """Scrape recent reviews from Apple App Store RSS feed."""
    reviews = []
    url = f"https://itunes.apple.com/us/rss/customerreviews/id={app_id}/sortBy=mostRecent/json"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            feed = data.get("feed", {})
            entries = feed.get("entry", [])
            
            # App Store returns a list of entries, but if there's only one it's a dict
            if isinstance(entries, dict):
                entries = [entries]
                
            for entry in entries:
                # Skip the first entry if it's the app metadata itself
                if "im:name" in entry:
                    continue
                    
                review_id_raw = entry.get("id", {}).get("label")
                if not review_id_raw:
                    continue
                    
                title = entry.get("title", {}).get("label", "")
                content = entry.get("content", {}).get("label", "")
                text = clean_text(f"{title} {content}")
                
                # Check ingestion filter
                if not any(kw in text.lower() for kw in KEYWORDS):
                    continue
                    
                updated_raw = entry.get("updated", {}).get("label")
                if updated_raw:
                    # App Store format: e.g. "2026-06-25T10:00:00-07:00"
                    # Simple parse or ISO fallback
                    timestamp = updated_raw
                else:
                    timestamp = datetime.now(timezone.utc).isoformat()
                    
                reviews.append({
                    "review_id": compute_md5(source, review_id_raw),
                    "source": source,
                    "timestamp": timestamp,
                    "text": text
                })
            print(f"Scraped {len(reviews)} matching reviews from {source}")
        else:
            print(f"App Store scrape returned status code {response.status_code}")
    except Exception as e:
        print(f"Non-breaking error during App Store scrape: {str(e)}")
        
    return reviews

def scrape_reddit(subreddit="spotify", source="Reddit"):
    """Scrape recent posts from Reddit using open .json feeds."""
    reviews = []
    url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=50"
    # Essential custom User-Agent to avoid HTTP 429
    headers = {"User-Agent": "AntigravityReviewDiscoveryEngine/1.0 (Growth PM Project)"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            posts = data.get("data", {}).get("children", [])
            for post in posts:
                post_data = post.get("data", {})
                post_id = post_data.get("id")
                if not post_id:
                    continue
                    
                title = post_data.get("title", "")
                selftext = post_data.get("selftext", "")
                text = clean_text(f"{title} {selftext}")
                
                # Check ingestion filter
                if not any(kw in text.lower() for kw in KEYWORDS):
                    continue
                    
                created_utc = post_data.get("created_utc")
                if created_utc:
                    timestamp = datetime.fromtimestamp(created_utc, timezone.utc).isoformat()
                else:
                    timestamp = datetime.now(timezone.utc).isoformat()
                    
                reviews.append({
                    "review_id": compute_md5(source, post_id),
                    "source": source,
                    "timestamp": timestamp,
                    "text": text
                })
            print(f"Scraped {len(reviews)} matching posts from {source} (r/{subreddit})")
        else:
            print(f"Reddit scrape returned status code {response.status_code}")
    except Exception as e:
        print(f"Non-breaking error during Reddit scrape: {str(e)}")
        
    return reviews

def scrape_google_play(app_id="com.spotify.music", source="Google Play"):
    """Scrape reviews from Google Play Store using google-play-scraper."""
    reviews_list = []
    try:
        from google_play_scraper import reviews as gp_reviews, Sort
        print(f"Scraping Google Play Store for {app_id}...")
        # Fetch 150 newest reviews
        result, _ = gp_reviews(
            app_id,
            lang='en',
            country='us',
            sort=Sort.NEWEST,
            count=150
        )
        for r in result:
            review_id_raw = r.get("reviewId")
            if not review_id_raw:
                continue
            content = r.get("content", "")
            text = clean_text(content)
            
            # Check ingestion filter
            if not any(kw in text.lower() for kw in KEYWORDS):
                continue
                
            at_dt = r.get("at")
            if at_dt:
                if at_dt.tzinfo is None:
                    at_dt = at_dt.replace(tzinfo=timezone.utc)
                timestamp = at_dt.isoformat()
            else:
                timestamp = datetime.now(timezone.utc).isoformat()
                
            reviews_list.append({
                "review_id": compute_md5(source, review_id_raw),
                "source": source,
                "timestamp": timestamp,
                "text": text
            })
        print(f"Scraped {len(reviews_list)} matching reviews from Google Play ({app_id})")
    except Exception as e:
        print(f"Non-breaking error during Google Play scrape for {app_id}: {str(e)}")
        
    return reviews_list

# --- LLM Processing & Parsing ---

def rule_based_fallback(text):
    """Fallback local classification when Groq API is unavailable or in test mode."""
    text_lower = text.lower()
    
    # Heuristic check for positive sentiment
    pos_words = ["love", "great", "satisfied", "excellent", "good", "perfect", "awesome", "best"]
    neg_words = ["crash", "worst", "terrible", "hate", "issue", "bug", "fail", "bad", "frustrat", "annoy", "loop", "clutter", "same songs"]
    
    is_positive = any(pw in text_lower for pw in pos_words) and not any(nw in text_lower for nw in neg_words)
    
    if is_positive:
        theme = "Positive"
        if "recommend" in text_lower or "preference" in text_lower or "sound" in text_lower or "study" in text_lower:
            theme = "Accurate Recommendations"
        elif "ui" in text_lower or "ux" in text_lower or "smooth" in text_lower or "beautiful" in text_lower:
            theme = "Great UI/UX"
        elif "playlist" in text_lower or "mix" in text_lower or "curat" in text_lower:
            theme = "Smart Curation"
            
        return {
            "theme": theme,
            "sentiment": "Positive",
            "user_type": "Casual Listener" if "casual" in text_lower else "Power User",
            "root_cause": "User is satisfied with the app"
        }
        
    # Defaults
    theme = "Echo Chamber"
    sentiment = "Negative"
    user_type = "Power User"
    root_cause = "Trapped in repetitive listening loop"
    
    if "smart shuffle" in text_lower or "shuffle" in text_lower:
        theme = "Smart Shuffle Failure"
        sentiment = "Highly Frustrated"
        user_type = "Playlist Curator"
        root_cause = "Smart shuffle repeats tracks repeatedly"
    elif "blend" in text_lower or "genre" in text_lower:
        theme = "Niche Genre Blending"
        sentiment = "Disappointed"
        user_type = "Audiophile"
        root_cause = "Algorithmic blending mixes unrelated genres"
    elif "ad" in text_lower or "ads" in text_lower or "commercial" in text_lower:
        theme = "UI/UX Clutter"
        sentiment = "Negative"
        user_type = "Casual Listener"
        root_cause = "Excessive or unskippable advertisements"
    elif "ui" in text_lower or "ux" in text_lower or "clutter" in text_lower:
        theme = "UI/UX Clutter"
        sentiment = "Negative"
        user_type = "Casual Listener"
        root_cause = "Cluttered UI interferes with play"
    elif "loop" in text_lower or "same songs" in text_lower:
        theme = "Echo Chamber"
        sentiment = "Highly Frustrated"
        user_type = "Power User"
        root_cause = "Algorithm loops identical songs repeatedly"
        
    return {
        "theme": theme,
        "sentiment": sentiment,
        "user_type": user_type,
        "root_cause": root_cause
    }

def clean_llm_json(response_text):
    """Safely extract valid JSON content within outermost braces."""
    try:
        # Find first '{' and last '}'
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        if start_idx == -1 or end_idx == -1:
            return None
        
        json_str = response_text[start_idx:end_idx + 1]
        # Parse and return
        data = json.loads(json_str)
        return data
    except Exception:
        return None

def analyze_review_with_groq(text):
    """Classify a review using Groq SDK."""
    api_key = os.getenv("GROQ_API_KEY")
    if api_key is None:
        api_key = GROQ_API_KEY
    if not api_key:
        # Transparent rule-based fallback if no key is configured
        return rule_based_fallback(text)
        
    from groq import Groq
    try:
        client = Groq(api_key=api_key)
        prompt = f"""You are a Growth PM and Data Architect. Analyze this music app user review:
"{text}"

First, determine if the review is primarily Positive/Neutral (the user is satisfied, praises the app, or lists no issues/frustrations) or Negative (complaining about features, finding bugs, listing design flaws, or experiencing frustrations).

If the review is Positive/Neutral, classify it exactly as follows:
- theme: "Accurate Recommendations" | "Great UI/UX" | "Smart Curation" | "Positive"
- sentiment: "Positive"
- user_type: "Power User" | "Casual Listener" | "Audiophile" | "Playlist Curator" (choose the most matching cohort based on their usage profile described in the review)
- root_cause: A concise 5-to-7 word description summarizing why they are satisfied.

If the review is Negative, classify it exactly as follows:
- theme: "Echo Chamber" | "Smart Shuffle Failure" | "Niche Genre Blending" | "UI/UX Clutter"
- sentiment: "Negative" | "Highly Frustrated" | "Disappointed"
- user_type: "Power User" | "Casual Listener" | "Audiophile" | "Playlist Curator"
- root_cause: A concise 5-to-7 word description of the exact, specific mechanical defect they are experiencing. Avoid generic descriptions like "Stale recommendations" or "Smart shuffle failure". Be highly specific to the user's scenario. For example, if a user cleared their liked list but the taste profile didn't update, write "Taste profile persists library reset". If they complain about ads interrupting music, write "Excessive ads interrupt song listening".

Output ONLY a raw, valid JSON object with keys: "theme", "sentiment", "user_type", "root_cause".
Do NOT include markdown formatting, backticks, or conversational text.
"""
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=GROQ_MODEL,
            temperature=0.1,
            max_tokens=150
        )
        response_text = chat_completion.choices[0].message.content
        result = clean_llm_json(response_text)
        
        if result:
            # Validate enums
            if result.get("theme") not in THEME_ENUM:
                result["theme"] = "Echo Chamber"
            if result.get("sentiment") not in SENTIMENT_ENUM:
                result["sentiment"] = "Negative"
            if result.get("user_type") not in USER_TYPE_ENUM:
                result["user_type"] = "Power User"
            # Ensure root_cause length or existence
            if not result.get("root_cause"):
                result["root_cause"] = "User is satisfied with the app" if result["theme"] == "Positive" else "Unspecified recommendation blocker"
            return result
            
    except Exception as e:
        print(f"Error calling Groq API: {str(e)}")
        
    # Final fallback on API or parsing failures
    return rule_based_fallback(text)

# --- Core Pipeline Runner ---

def run_pipeline():
    """Main function orchestrating the full ingestion and analysis loop."""
    print("Starting AI-Native Review Discovery Engine Pipeline...")
    
    # 1. Scraping Ingestion
    scraped_reviews = []
    
    # Spotify App Store reviews
    scraped_reviews.extend(scrape_app_store(app_id="324684580", source="App Store"))
    
    # Spotify Reddit posts
    scraped_reviews.extend(scrape_reddit(subreddit="spotify", source="Reddit"))
    
    # Spotify Google Play reviews
    scraped_reviews.extend(scrape_google_play(app_id="com.spotify.music", source="Google Play"))
    
    if not scraped_reviews:
        print("No new reviews scraped in this execution.")
    else:
        print(f"Scraped total {len(scraped_reviews)} matching reviews.")
        
    # 2. Database Sync - Ingest Raw Data
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Supabase credentials not configured. pipeline.py running in Dry-Run mode.")
        print("Scraped raw reviews:")
        print(json.dumps(scraped_reviews[:3], indent=2))
        return
        
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Batch upsert to public.raw_feedback
    if scraped_reviews:
        try:
            print("Upserting raw reviews to Supabase...")
            # Supabase API handles list upsert
            supabase.table("raw_feedback").upsert(scraped_reviews, on_conflict="review_id").execute()
            print("Raw reviews successfully upserted.")
        except Exception as e:
            print(f"Failed to upsert raw reviews to Supabase: {str(e)}")
            
    # 3. Retrieve Delta State from public.unprocessed_feedback
    print("Fetching unprocessed delta reviews from database...")
    try:
        response = supabase.table("unprocessed_feedback").select("review_id, text").execute()
        unprocessed_records = response.data
        print(f"Found {len(unprocessed_records)} unprocessed reviews.")
    except Exception as e:
        print(f"Failed to fetch unprocessed feedback view: {str(e)}")
        return
        
    if not unprocessed_records:
        print("Delta is zero. No records need AI classification.")
        return
        
    # 4. Process Delta with Throttled Groq LLM Loop
    analytics_records = []
    processed_count = 0
    
    for record in unprocessed_records:
        if processed_count >= MAX_BATCH_SIZE:
            print(f"Reached batch limit ceiling of {MAX_BATCH_SIZE} records. Terminating run.")
            break
            
        review_id = record["review_id"]
        text = record["text"]
        
        print(f"[{processed_count + 1}/{len(unprocessed_records)}] Analyzing review_id: {review_id}")
        
        # Call Groq (with auto fallback)
        analysis = analyze_review_with_groq(text)
        
        analytics_records.append({
            "review_id": review_id,
            "theme": analysis["theme"],
            "sentiment": analysis["sentiment"],
            "user_type": analysis["user_type"],
            "root_cause": analysis["root_cause"]
        })
        
        processed_count += 1
        
        # Enforce rate limit (skip sleep on last item or if running local fallback without key)
        if GROQ_API_KEY and processed_count < len(unprocessed_records):
            time.sleep(RPM_DELAY)
            
    # 5. Push Analysis to public.ai_analytics
    if analytics_records:
        try:
            print(f"Uploading {len(analytics_records)} processed records to ai_analytics...")
            supabase.table("ai_analytics").upsert(analytics_records, on_conflict="review_id").execute()
            print("AI analysis successfully backfilled.")
        except Exception as e:
            print(f"Failed to upload AI analytics records: {str(e)}")

if __name__ == "__main__":
    run_pipeline()
