#!/usr/bin/env python
"""
Verification Script - Checks Supabase tables and Groq API connectivity.
"""

import os
import sys
from dotenv import load_dotenv
from supabase import create_client, Client

# Load env file
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

print("=== AI-Native Review Discovery Engine Diagnostics ===")

# 1. Check Env Variables
missing = []
if not SUPABASE_URL or "your-project-id" in SUPABASE_URL:
    missing.append("SUPABASE_URL")
if not SUPABASE_KEY or "your-supabase-service-role" in SUPABASE_KEY:
    missing.append("SUPABASE_KEY")
if not GROQ_API_KEY or "your_groq_api_key" in GROQ_API_KEY:
    missing.append("GROQ_API_KEY")

if missing:
    print(f"ERROR: Missing or placeholder environment variables in .env: {', '.join(missing)}")
    sys.exit(1)
else:
    print("SUCCESS: Environment variables are set.")

# 2. Check Supabase Connectivity
try:
    print("Connecting to Supabase...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("SUCCESS: Connected to Supabase API client.")
except Exception as e:
    print(f"ERROR: Failed to initialize Supabase client: {str(e)}")
    sys.exit(1)

# 3. Check Database Tables and Views
db_ready = True
tables_to_check = ["raw_feedback", "ai_analytics", "unprocessed_feedback"]

for target in tables_to_check:
    try:
        # Perform a limit-1 select query to see if table/view exists
        response = supabase.table(target).select("*").limit(1).execute()
        print(f"SUCCESS: Table/View '{target}' exists and is accessible.")
    except Exception as e:
        print(f"ERROR: Table/View '{target}' is not accessible or does not exist: {str(e)}")
        db_ready = False

if not db_ready:
    print("\nACTION REQUIRED: Please copy the content of 'setup.sql' and execute it in your Supabase SQL Editor.")
    sys.exit(1)
else:
    print("SUCCESS: Supabase schema is fully ready.")

# 4. Check Groq API Connectivity
if GROQ_API_KEY:
    print("Connecting to Groq API...")
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        # Test request with small model
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        print(f"Sending test completion request to Groq using model: {model}...")
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": "Respond with the word 'OK' only."}],
            model=model,
            max_tokens=10,
            temperature=0.1
        )
        resp = chat_completion.choices[0].message.content.strip()
        print(f"SUCCESS: Groq API response: '{resp}'")
    except Exception as e:
        print(f"ERROR: Groq API call failed: {str(e)}")
        sys.exit(1)

print("\n=== SYSTEM IS 100% READY ===")
