import os
import re
import hashlib
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv
import db_client

load_dotenv()

# Configurable Targets (Blinkit)
PLAY_STORE_APP_ID = "com.grofers.customerapp"
APP_STORE_APP_ID = "960335206"

# Reddit OAuth Feature Flag
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "BlinkitCategoryExplorerScraper/1.0")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")

# Seed Reddit subreddits and search queries for category exploration / quick commerce discussions
REDDIT_SUBREDDITS = ["india", "bangalore", "delhi", "mumbai", "IndianFoodieClub", "gurgaon"]
REDDIT_SEARCH_QUERIES = ["Blinkit category", "Blinkit recommendation", "Blinkit explore", "Blinkit vegetables", "Blinkit items"]
REDDIT_SEED_URLS = [
    "https://www.reddit.com/r/india/comments/z8564s/blinkit_zepto_instamart_which_is_better/",
    "https://www.reddit.com/r/bangalore/comments/x90w81/grocery_delivery_apps_zepto_vs_blinkit_vs/"
]

def clean_text(text):
    """Sanitize text and limit length to 800 characters to optimize LLM context window cost."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text[:800].strip()

def compute_md5(source, platform_id):
    """Compute deterministic MD5 hash for review deduplication."""
    hasher = hashlib.md5()
    hasher.update(f"{source}:{platform_id}".encode("utf-8"))
    return hasher.hexdigest()

def filter_by_keywords(text, keywords):
    """Check if the text contains any of the active filter keywords (case-insensitive)."""
    if not keywords:
        return True
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)

def get_simulated_scraped_data(source, count=20):
    """Zero-synthetic policy: Returns an empty list to prevent synthetic backfilling."""
    print(f"[Zero-Synthetic Policy] Mock/synthetic data generation disabled for {source}.")
    return []

def scrape_play_store(limit=150):
    """Scrape reviews from Google Play Store for Blinkit with keyword expansion and fallback stuffing."""
    reviews_list = []
    active_keywords = db_client.fetch_keywords()
    seen_ids = set()
    
    try:
        from google_play_scraper import reviews as gp_reviews, Sort
        print(f"[Play Store Scraper] Scraping up to {limit} reviews for {PLAY_STORE_APP_ID}...")
        
        # Query a larger volume from both NEWEST and MOST_RELEVANT to get a diverse set of reviews
        fetch_count = max(limit * 6, 300)
        
        results_newest = []
        try:
            results_newest, _ = gp_reviews(
                PLAY_STORE_APP_ID,
                lang='en',
                country='in',
                sort=Sort.NEWEST,
                count=fetch_count
            )
        except Exception as e:
            print(f"[Play Store Scraper] NEWEST sort query failed: {e}")
            
        results_relevant = []
        try:
            results_relevant, _ = gp_reviews(
                PLAY_STORE_APP_ID,
                lang='en',
                country='in',
                sort=Sort.MOST_RELEVANT,
                count=fetch_count
            )
        except Exception as e:
            print(f"[Play Store Scraper] MOST_RELEVANT sort query failed: {e}")
            
        all_results = results_newest + results_relevant
        
        for r in all_results:
            review_id_raw = r.get("reviewId")
            if not review_id_raw:
                continue
                
            review_id = compute_md5("Google Play", review_id_raw)
            if review_id in seen_ids:
                continue
                
            content = r.get("content", "")
            text = clean_text(content)
            
            # Keywords matching
            if not filter_by_keywords(text, active_keywords):
                continue
                
            at_dt = r.get("at")
            if at_dt:
                if at_dt.tzinfo is None:
                    at_dt = at_dt.replace(tzinfo=timezone.utc)
                timestamp = at_dt.isoformat()
            else:
                timestamp = datetime.now(timezone.utc).isoformat()
                
            seen_ids.add(review_id)
            reviews_list.append({
                "review_id": review_id,
                "source": "Google Play",
                "timestamp": timestamp,
                "text": text,
                "app_version_approx": r.get("reviewCreatedVersion", "Unknown")
            })
            
            if len(reviews_list) >= limit:
                break
                
        print(f"[Play Store Scraper] Ingested {len(reviews_list)} matching reviews from Play Store.")
    except Exception as e:
        print(f"[Play Store Scraper] Live scraper failed completely: {e}")
    return reviews_list

def scrape_app_store(limit=100):
    """Scrape reviews from Apple App Store RSS feed for Blinkit (India) with paging and fallback stuffing."""
    reviews_list = []
    active_keywords = db_client.fetch_keywords()
    seen_ids = set()
    
    try:
        print(f"[App Store Scraper] Scraping up to {limit} reviews for App ID {APP_STORE_APP_ID}...")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        
        # Page through 10 pages of App Store RSS feed to fetch a larger window of reviews (50 reviews per page)
        for page in range(1, 11):
            url = f"https://itunes.apple.com/in/rss/customerreviews/id={APP_STORE_APP_ID}/page={page}/sortBy=mostRecent/json"
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                feed = data.get("feed", {})
                entries = feed.get("entry", [])
                
                if isinstance(entries, dict):
                    entries = [entries]
                    
                for entry in entries:
                    if "im:name" in entry:
                        continue
                        
                    review_id_raw = entry.get("id", {}).get("label")
                    if not review_id_raw:
                        continue
                        
                    review_id = compute_md5("App Store", review_id_raw)
                    if review_id in seen_ids:
                        continue
                        
                    title = entry.get("title", {}).get("label", "")
                    content = entry.get("content", {}).get("label", "")
                    text = clean_text(f"{title} {content}")
                    
                    if not filter_by_keywords(text, active_keywords):
                        continue
                        
                    updated_raw = entry.get("updated", {}).get("label")
                    timestamp = updated_raw if updated_raw else datetime.now(timezone.utc).isoformat()
                    
                    version_raw = entry.get("im:version", {}).get("label", "Unknown")
                    
                    seen_ids.add(review_id)
                    reviews_list.append({
                        "review_id": review_id,
                        "source": "App Store",
                        "timestamp": timestamp,
                        "text": text,
                        "app_version_approx": version_raw
                    })
                    
                    if len(reviews_list) >= limit:
                        break
            else:
                print(f"[App Store Scraper] RSS feed page {page} returned HTTP {response.status_code}")
                break
                
            if len(reviews_list) >= limit:
                break
                
        print(f"[App Store Scraper] Ingested {len(reviews_list)} matching reviews from Apple Store.")
    except Exception as e:
        print(f"[App Store Scraper] Live scraper failed completely: {e}")
        
    return reviews_list

def scrape_reddit(limit=75):
    """Scrape comments and posts from curated Reddit threads and subreddits using PRAW."""
    reviews_list = []
    active_keywords = db_client.fetch_keywords()
    seen_ids = set()
    
    if not (REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET):
        print(f"[Reddit Scraper] OAuth credentials missing. Returning {len(reviews_list)} reviews under zero-synthetic policy.")
        return reviews_list
        
    try:
        import praw
        print("[Reddit Scraper] OAuth credentials found. Authenticating with Reddit API via PRAW...")
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT,
            username=REDDIT_USERNAME,
            password=REDDIT_PASSWORD
        )
        
        # 1. Search across target subreddits for Blinkit queries
        for sub_name in REDDIT_SUBREDDITS:
            try:
                subreddit = reddit.subreddit(sub_name)
                for query in REDDIT_SEARCH_QUERIES:
                    print(f"[Reddit Scraper] Searching r/{sub_name} for '{query}'...")
                    for submission in subreddit.search(query, limit=10):
                        submission.comments.replace_more(limit=0)
                        for comment in submission.comments[:5]:
                            review_id = compute_md5("Reddit", comment.id)
                            if review_id in seen_ids:
                                continue
                                
                            text = clean_text(comment.body)
                            if not filter_by_keywords(text, active_keywords):
                                continue
                                
                            timestamp = datetime.fromtimestamp(comment.created_utc, timezone.utc).isoformat()
                            
                            seen_ids.add(review_id)
                            reviews_list.append({
                                "review_id": review_id,
                                "source": "Reddit",
                                "timestamp": timestamp,
                                "text": text,
                                "app_version_approx": "N/A"
                            })
                            if len(reviews_list) >= limit:
                                break
                    if len(reviews_list) >= limit:
                        break
            except Exception as e_sub:
                print(f"[Reddit Scraper] Subreddit r/{sub_name} search notice: {e_sub}")
            if len(reviews_list) >= limit:
                break

        # 2. Seed URLs fallback search
        if len(reviews_list) < limit:
            for url in REDDIT_SEED_URLS:
                print(f"[Reddit Scraper] Scraping seed thread: {url}")
                submission = reddit.submission(url=url)
                submission.comments.replace_more(limit=0)
                for comment in submission.comments:
                    review_id = compute_md5("Reddit", comment.id)
                    if review_id in seen_ids:
                        continue
                        
                    text = clean_text(comment.body)
                    if not filter_by_keywords(text, active_keywords):
                        continue
                        
                    timestamp = datetime.fromtimestamp(comment.created_utc, timezone.utc).isoformat()
                    
                    seen_ids.add(review_id)
                    reviews_list.append({
                        "review_id": review_id,
                        "source": "Reddit",
                        "timestamp": timestamp,
                        "text": text,
                        "app_version_approx": "N/A"
                    })
                    if len(reviews_list) >= limit:
                        break
                if len(reviews_list) >= limit:
                    break

        print(f"[Reddit Scraper] Ingested {len(reviews_list)} matching comments from Reddit.")
    except Exception as e:
        print(f"[Reddit Scraper] PRAW extraction failed: {e}")
        
    return reviews_list
