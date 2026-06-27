#!/usr/bin/env python
"""
Utility script to clear all data in public.raw_feedback (and cascade to ai_analytics)
to prepare for clean production scraping.
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: Supabase credentials not found in environment.")
    exit(1)

print("Connecting to Supabase...")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print("Clearing public.raw_feedback (cascading to ai_analytics)...")
try:
    # Delete all rows by using a filter that is always true
    response = supabase.table("raw_feedback").delete().neq("review_id", "0").execute()
    print("Database successfully cleared of all reviews and analysis records.")
except Exception as e:
    print(f"Error clearing database: {str(e)}")
