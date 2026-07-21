import os
import re
import json
import hashlib
import random
import time
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

# Load env variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PLAY_STORE_APP_ID = "com.grofers.customerapp"
APP_STORE_APP_ID = "1212852256"

# Keywords for category exploration & rubrics
KEYWORDS = [
    "category", "explore", "recommend", "reorder", "never tried",
    "search", "browse", "out of stock", "substitute", "finding",
    "navigation", "layout", "fresh", "vegetables", "groceries",
    "fruits", "delivery", "clutter", "widget", "item", "snacks",
    "beverages", "dairy", "checkout", "aisle", "section", "pet",
    "personal care", "baby", "shampoo", "diapers", "dog food"
]

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text[:800].strip()

def compute_md5(source, platform_id):
    hasher = hashlib.md5()
    hasher.update(f"{source}:{platform_id}".encode("utf-8"))
    return hasher.hexdigest()

def scrape_real_play_store(count=5000):
    """Scrape up to 5000 recent reviews from Google Play Store for Blinkit."""
    reviews = []
    try:
        from google_play_scraper import reviews as gp_reviews, Sort
        print(f"Scraping Google Play Store for {PLAY_STORE_APP_ID} (fetching {count} reviews)...")
        result, _ = gp_reviews(
            PLAY_STORE_APP_ID,
            lang='en',
            country='in',
            sort=Sort.NEWEST,
            count=count
        )
        for r in result:
            review_id_raw = r.get("reviewId")
            if not review_id_raw:
                continue
            content = r.get("content", "")
            text = clean_text(content)
            
            # Match keywords
            text_lower = text.lower()
            if not any(kw in text_lower for kw in KEYWORDS):
                continue
                
            at_dt = r.get("at")
            if at_dt:
                if at_dt.tzinfo is None:
                    at_dt = at_dt.replace(tzinfo=timezone.utc)
                timestamp = at_dt.isoformat()
            else:
                timestamp = datetime.now(timezone.utc).isoformat()
                
            reviews.append({
                "review_id": compute_md5("Google Play", review_id_raw),
                "source": "Google Play",
                "timestamp": timestamp,
                "text": text,
                "app_version_approx": r.get("reviewCreatedVersion", "Unknown")
            })
        print(f"Scraped {len(reviews)} matching real Play Store reviews.")
    except Exception as e:
        print(f"Play Store scraping error: {e}")
    return reviews

def scrape_real_app_store():
    """Scrape RSS feed reviews for Blinkit from App Store India."""
    reviews = []
    url = f"https://itunes.apple.com/in/rss/customerreviews/id={APP_STORE_APP_ID}/sortBy=mostRecent/json"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        print(f"Scraping App Store India for app ID {APP_STORE_APP_ID}...")
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            entries = data.get("feed", {}).get("entry", [])
            if isinstance(entries, dict):
                entries = [entries]
            for entry in entries:
                if "im:name" in entry:
                    continue
                review_id = entry.get("id", {}).get("label")
                if not review_id:
                    continue
                title = entry.get("title", {}).get("label", "")
                content = entry.get("content", {}).get("label", "")
                text = clean_text(f"{title} {content}")
                
                if not any(kw in text.lower() for kw in KEYWORDS):
                    continue
                    
                updated = entry.get("updated", {}).get("label")
                timestamp = updated if updated else datetime.now(timezone.utc).isoformat()
                version = entry.get("im:version", {}).get("label", "Unknown")
                
                reviews.append({
                    "review_id": compute_md5("App Store", review_id),
                    "source": "App Store",
                    "timestamp": timestamp,
                    "text": text,
                    "app_version_approx": version
                })
        print(f"Scraped {len(reviews)} matching App Store reviews.")
    except Exception as e:
        print(f"App Store scraping error: {e}")
    return reviews

def main():
    print("=== Blinkit Reviews Scraper & Seeding Script (100% Real Scraping) ===")
    
    # 1. Scrape real reviews
    real_reviews = []
    real_reviews.extend(scrape_real_play_store(6000))  # Fetch 6000 reviews to guarantee a large sample
    real_reviews.extend(scrape_real_app_store())
    
    # Unique check
    seen_ids = set()
    unique_real = []
    for r in real_reviews:
        if r["review_id"] not in seen_ids:
            seen_ids.add(r["review_id"])
            unique_real.append(r)
            
    print(f"Total unique real matching reviews collected: {len(unique_real)}")
    
    if len(unique_real) < 500:
        print(f"WARNING: Collected only {len(unique_real)} matching reviews. Trying to push them anyway...")
    else:
        print(f"SUCCESS: Collected {len(unique_real)} matching reviews (greater than target 500 limit).")
        
    # 3. Connect to Supabase and seed in small batches for safety (step-by-step saving)
    if not SUPABASE_URL or not SUPABASE_KEY or "your-" in SUPABASE_URL:
        print("Supabase credentials missing or placeholder. Saving locally to 'blinkit_real_feedback.json'.")
        with open("blinkit_real_feedback.json", "w") as f:
            json.dump(unique_real, f, indent=2)
        return
        
    print(f"Connecting to Supabase instance at {SUPABASE_URL}...")
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/raw_feedback"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    
    batch_size = 50
    success_count = 0
    
    for i in range(0, len(unique_real), batch_size):
        batch = unique_real[i:i+batch_size]
        print(f"Uploading batch {i//batch_size + 1} ({len(batch)} records) to Supabase...")
        try:
            response = requests.post(url, headers=headers, json=batch, timeout=20)
            if response.status_code in [200, 201]:
                success_count += len(batch)
                print(f"Uploaded: {success_count}/{len(unique_real)} records successfully saved.")
            else:
                print(f"ERROR: Batch {i//batch_size + 1} failed. Status code: {response.status_code}")
                print(response.text)
        except Exception as e:
            print(f"EXCEPTION: Uploading batch {i//batch_size + 1} failed: {e}")
            
        time.sleep(1.0)
        
    print(f"\nSeeding complete. Successfully uploaded {success_count} 100% real reviews to Supabase.")

if __name__ == "__main__":
    main()
