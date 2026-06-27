#!/usr/bin/env python
"""
Utility script to analyze the 449 real Spotify reviews seeded in Supabase
and generate a PM expected results report.
"""

import os
from collections import Counter
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: Supabase credentials not found.")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Fetch all raw feedback rows
response = supabase.table("raw_feedback").select("source, text").execute()
data = response.data

print(f"Total reviews in database: {len(data)}")

sources = [r["source"] for r in data]
print("Source Distribution:", dict(Counter(sources)))

# Analyze keyword frequencies
keywords = ["smart shuffle", "shuffle", "loop", "same songs", "echo chamber", "algorithm", "discovery"]
keyword_matches = {kw: [] for kw in keywords}

for r in data:
    text_lower = r["text"].lower()
    for kw in keywords:
        if kw in text_lower:
            keyword_matches[kw].append(r["text"])

print("\n=== Keyword Matches ===")
for kw, matches in keyword_matches.items():
    print(f" - '{kw}': {len(matches)} reviews")

print("\n=== Sample Spotify User Complaints ===")
# Print a few samples of actual user reviews for context
print("\n[Smart Shuffle / Loop Complaints]")
shuffle_samples = [t for t in keyword_matches["smart shuffle"] + keyword_matches["loop"] if len(t) > 20]
for s in shuffle_samples[:3]:
    print(" ->", s)

print("\n[Echo Chamber / Same Songs Complaints]")
echo_samples = [t for t in keyword_matches["echo chamber"] + keyword_matches["same songs"] if len(t) > 20]
for s in echo_samples[:3]:
    print(" ->", s)

print("\n[Algorithm / Discovery Complaints]")
algo_samples = [t for t in keyword_matches["algorithm"] + keyword_matches["discovery"] if len(t) > 20]
for s in algo_samples[:3]:
    print(" ->", s)
