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

# Ingestion filter keywords (Default fallback list)
KEYWORDS = [
    "discovery", "recommendation", "smart shuffle", "shuffle", "algorithm", 
    "same songs", "echo chamber", "loop", "repeat", "ad", "ads", "slow", 
    "sluggish", "slop", "ai dj", "dj", "widget", "ui", "ux", "clutter", 
    "bugs", "glitch", "premium"
]

def load_keywords_from_supabase():
    """Fetch active filter keywords from Supabase filter_keywords table, updating KEYWORDS list in-place."""
    global KEYWORDS
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        response = supabase.table("filter_keywords").select("keyword").execute()
        if response.data:
            db_kws = [row["keyword"] for row in response.data]
            if db_kws:
                KEYWORDS.clear()
                KEYWORDS.extend(db_kws)
                print(f"Successfully loaded {len(KEYWORDS)} keywords from Supabase: {KEYWORDS}")
    except Exception as e:
        print(f"Could not load filter_keywords from Supabase (table may not exist yet, using static defaults): {str(e)}")

# Attempt to load keywords from DB at module import time
load_keywords_from_supabase()

# Allowed enums for validation
THEME_ENUM = [
    "Echo Chamber", "Smart Shuffle Failure", "Niche Genre Blending", "UI/UX Clutter",
    "Ad & Subscription Barriers", "App Performance & Crashes", "Offline Sync & Connection",
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
    
    def has_word(pattern, text):
        return bool(re.search(pattern, text))

    # Positive keywords (with word boundaries)
    pos_patterns = [
        r"\blove(s|d|ly|ing)?\b",
        r"\bgreat(er|est|ly)?\b",
        r"\b(satisfied|satisfaction)\b",
        r"\bexcellent(ly)?\b",
        r"\bgood(ness)?\b",
        r"\bperfect(ly)?\b",
        r"\bawesome\b",
        r"\bbest\b"
    ]
    
    # Negative keywords (with word boundaries)
    neg_patterns = [
        r"\bcrash(es|ed|ing)?\b",
        r"\bworst\b",
        r"\bterrible(y)?\b",
        r"\bhate(s|d|ful)?\b",
        r"\bissue(s)?\b",
        r"\bbug(s|gy)?\b",
        r"\bfail(ed|ing|ure|ures)?\b",
        r"\bbad(ly)?\b",
        r"\bfrustrat(e|ed|es|ing|ion|ions)?\b",
        r"\bannoy(s|ed|ing|ance|ances)?\b",
        r"\bloop(s|ed|ing)?\b",
        r"\bclutter(ed)?\b",
        r"\bsame songs\b",
        r"\bcriticis(m|ms|e|ed|ing)\b",
        r"\bcriticiz(e|ed|es|ing)\b",
        r"\bcomplain(t|ts|ed|ing|s)?\b",
        r"\b[1-3]\s*star(s)?\b",
        r"\bdisappointed\b",
        r"\bdisappointing\b"
    ]
    
    # Check if any positive or negative patterns match
    has_pos = any(has_word(pat, text_lower) for pat in pos_patterns)
    has_neg = any(has_word(pat, text_lower) for pat in neg_patterns)
    
    # Negation check for positive words (e.g. "not good", "no love", "not satisfied")
    negation_patterns = [
        r"\bnot\s+(good|great|perfect|satisfied|excellent|awesome|best|love)\b",
        r"\bno\s+love\b",
        r"\b(un|dis)satisfied\b",
        r"\bimperfect\b"
    ]
    has_negation = any(has_word(pat, text_lower) for pat in negation_patterns)
    
    # Primarily positive if it has positive indicators, and NO negative indicators or negations
    is_positive = has_pos and not (has_neg or has_negation)
    
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
    
    # Feature-specific negative checks
    has_ad_barrier = any(has_word(pat, text_lower) for pat in [
        r"\b(ad|ads|commercial|commercials|premium|pay|paying|payment|subscription|subscriptions|subscribe|money|free|paywall|paywalls|restrict|restricted|restriction|restrictions|limit|limits|limited)\b"
    ])
    has_shuffle = any(has_word(pat, text_lower) for pat in [r"\bshuffle\b", r"\bsmart\s+shuffle\b"])
    has_blend = any(has_word(pat, text_lower) for pat in [r"\b(blend|blending|genre|genres)\b"])
    has_performance = any(has_word(pat, text_lower) for pat in [
        r"\b(crash|crashes|crashing|freeze|freezes|freezing|lag|lags|lagging|slow|slowness|hang|hangs|hanging|stop|stops|stopped|stopping)\b"
    ])
    has_offline = any(has_word(pat, text_lower) for pat in [
        r"\b(offline|download|downloads|downloaded|downloading|wifi|connection|connectivity|internet)\b"
    ])
    has_ui_clutter = any(has_word(pat, text_lower) for pat in [
        r"\b(ui|ux|clutter|cluttered|layout|interface|design)\b"
    ])
    
    if has_ad_barrier:
        theme = "Ad & Subscription Barriers"
        sentiment = "Negative"
        user_type = "Casual Listener"
        root_cause = "Premium constraints or excessive advertisements"
    elif has_shuffle:
        theme = "Smart Shuffle Failure"
        sentiment = "Highly Frustrated"
        user_type = "Playlist Curator"
        root_cause = "Smart shuffle repeats tracks repeatedly"
    elif has_blend:
        theme = "Niche Genre Blending"
        sentiment = "Disappointed"
        user_type = "Audiophile"
        root_cause = "Algorithmic blending mixes unrelated genres"
    elif has_performance:
        theme = "App Performance & Crashes"
        sentiment = "Highly Frustrated"
        user_type = "Power User"
        root_cause = "Application crashes or severe performance lag"
    elif has_offline:
        theme = "Offline Sync & Connection"
        sentiment = "Disappointed"
        user_type = "Casual Listener"
        root_cause = "Offline playback or connectivity errors"
    elif has_ui_clutter:
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
        client = Groq(api_key=api_key, timeout=6.0)
        prompt = f"""You are a Growth PM and Data Architect. Analyze this music app user review:
"{text}"

First, determine if the review is primarily Positive/Neutral (the user is satisfied, praises the app, or lists no issues/frustrations) or Negative (complaining about features, finding bugs, listing design flaws, or experiencing frustrations).

CRITICAL: If a review contains mixed sentiment, such as praising the UI or recommendation algorithm but also expressing clear frustrations, criticisms, or complaints (e.g., complaining about advertisements, premium/subscription locks, song change restrictions, forced shuffling, crashes, or offline issues), you MUST classify the review as Negative.

If the review is Positive/Neutral, classify it exactly as follows:
- theme: Choose one of:
  * "Accurate Recommendations": Praise for recommendations, discovery, or algorithms.
  * "Great UI/UX": Praise for design, look and feel, or layout.
  * "Smart Curation": Praise for playlist curation, mixes, or radios.
  * "Positive": General praise with no specific theme.
- sentiment: "Positive"
- user_type: "Power User" | "Casual Listener" | "Audiophile" | "Playlist Curator" (choose the most matching cohort based on their usage profile described in the review)
- root_cause: A concise 5-to-7 word description summarizing why they are satisfied.

If the review is Negative, classify it exactly as follows:
- theme: Choose the most appropriate theme based on these semantic definitions:
  * "Ad & Subscription Barriers": Complaints about ads, paywalls/premium restrictions (including free-tier restrictions like forced shuffling of playlists/albums, limits on skips, preview-only mode, or locked queue control).
  * "Smart Shuffle Failure": Specific issues where the smart shuffle algorithm repeats the same tracks, loops, fails technically, or has toggling issues.
  * "Echo Chamber": The recommendation algorithm (Daily Mixes, Discover Weekly, DJ, etc.) is stale, repetitive, or traps the user in a loop of the same songs.
  * "Niche Genre Blending": Disliked mixing of unrelated or jarring genres in blend playlists.
  * "UI/UX Clutter": UI layout is cluttered, confusing, unintuitive, or hard to navigate.
  * "App Performance & Crashes": App freezes, crashes, lags, or is slow.
  * "Offline Sync & Connection": Issues with offline mode, downloading, or network connectivity.
- sentiment: "Negative" | "Highly Frustrated" | "Disappointed"
- user_type: "Power User" | "Casual Listener" | "Audiophile" | "Playlist Curator"
- root_cause: A concise 5-to-7 word description of the exact, specific mechanical defect they are experiencing. Avoid generic descriptions like "Stale recommendations" or "Smart shuffle failure". Be highly specific to the user's scenario. For example, if a user cleared their liked list but the taste profile didn't update, write "Taste profile persists library reset". If they complain about ads interrupting music, write "Excessive ads interrupt song listening".

Few-shot examples for reference:
Example 1 (Forced Shuffle on Free tier):
Review: "I hate that Spotify free forces shuffle and I can't play the songs in order unless I pay."
Output: {{"theme": "Ad & Subscription Barriers", "sentiment": "Negative", "user_type": "Casual Listener", "root_cause": "Forced shuffle on free tier"}}

Example 2 (Smart Shuffle repetition bug):
Review: "The smart shuffle is broken, it keeps playing the same 3 songs over and over again on my playlist."
Output: {{"theme": "Smart Shuffle Failure", "sentiment": "Highly Frustrated", "user_type": "Playlist Curator", "root_cause": "Smart shuffle repeats tracks repeatedly"}}

Example 3 (Mixed sentiment with paywall constraint):
Review: "It's a great app with amazing recommendations, but 2 stars because shuffle is a premium feature and I'm forced to shuffle playlists."
Output: {{"theme": "Ad & Subscription Barriers", "sentiment": "Negative", "user_type": "Casual Listener", "root_cause": "Playlist shuffle locked behind premium"}}

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
