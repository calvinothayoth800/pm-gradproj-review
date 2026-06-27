#!/usr/bin/env python
"""
Utility script to clear all records from public.ai_analytics.
Resets the classification state of all raw reviews using built-in urllib
to call the Supabase PostgREST API directly, avoiding pip dependency issues.
"""

import os
import urllib.request
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: Supabase credentials not found in environment.")
    exit(1)

# Format the REST endpoint URL
# Postgrest syntax for not equal is: ?column=neq.value
rest_url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/ai_analytics?review_id=neq.0"

req = urllib.request.Request(
    rest_url,
    headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    },
    method="DELETE"
)

print("Connecting directly to Supabase REST API...")
try:
    with urllib.request.urlopen(req) as response:
        status = response.status
        print(f"SUCCESS: AI analytics table successfully cleared (HTTP Status: {status}).")
        print("All raw reviews are now marked as unprocessed and ready for classification!")
except Exception as e:
    print(f"Error clearing database via REST API: {str(e)}")
