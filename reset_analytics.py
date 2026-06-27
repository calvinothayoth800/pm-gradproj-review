#!/usr/bin/env python
"""
Utility script to clear all records from public.ai_analytics.
This resets the classification state of all raw reviews, marking them
as "unprocessed" so they can be classified again using the updated pipeline.
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

print("Clearing public.ai_analytics...")
try:
    # Delete all rows from ai_analytics by selecting everything that isn't ID 0
    response = supabase.table("ai_analytics").delete().neq("review_id", "0").execute()
    print("SUCCESS: AI analytics table successfully cleared.")
    print("All raw reviews are now marked as unprocessed and ready for classification!")
except Exception as e:
    print(f"Error clearing database: {str(e)}")
