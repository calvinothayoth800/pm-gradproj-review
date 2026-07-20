import os
import json
import random
from dotenv import load_dotenv
import db_client

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", GROQ_API_KEY)
    except Exception:
        pass
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Default high-quality static keywords fallback for Blinkit category exploration
DEFAULT_KEYWORDS = [
    "category", "explore", "recommend", "reorder", "never tried",
    "search", "browse", "out of stock", "substitute", "finding",
    "navigation", "layout", "fresh", "vegetables", "groceries",
    "fruits", "delivery", "slop", "clutter", "widget", "item",
    "snacks", "beverages", "dairy", "checkout", "aisle", "section"
]

def run_query_strategist(sample_records):
    """
    Query Strategist Agent:
    Analyzes a 100-record sample of raw feedback to propose expanded keywords
    describing user category exploration behaviors on Blinkit.
    """
    print(f"[Query Strategist] Running analysis on {len(sample_records)} raw feedback sample...")
    
    if not sample_records:
        print("[Query Strategist] No records provided for sampling. Using default keyword list.")
        db_client.insert_keywords(DEFAULT_KEYWORDS)
        return DEFAULT_KEYWORDS
        
    if not GROQ_API_KEY:
        print("[Query Strategist] Groq API Key missing. Falling back to default list.")
        db_client.insert_keywords(DEFAULT_KEYWORDS)
        return DEFAULT_KEYWORDS

    # Extract raw text from samples
    texts = [r["text"] for r in sample_records[:100]]
    prompt = f"""
You are an expert Growth Product Manager and Data Scientist at a Quick-Commerce app like Blinkit, Zepto, or Instamart.
Your task is to analyze user reviews and suggest keywords and search phrases that capture user behaviors, patterns, and issues related to "Category Exploration".
Category exploration includes browsing specific sections (e.g., Vegetables, Dairy, Snacks), discovering new categories, finding items, navigation issues, reordering habits, interactions with recommendation widgets, out-of-stock item handling, and searching vs browsing.

Here is a 100-review sample from our users:
{json.dumps(texts, indent=2)}

Based on these reviews, suggest an expanded list of 20-30 clean, single-word or short-phrase search keywords (e.g., "reorder", "substitutes", "fruits", "widget", "categories") that are highly relevant to category discovery and navigation issues.
Avoid very generic words like "good", "bad", "app", "blinkit", "zepto". Focus on features, navigation UI, product cohorts, and grocery categories.

Output ONLY a valid JSON list of strings. Do not include markdown blocks, backticks, or any conversational text.
Example output format: ["keyword1", "keyword2", "keyword3"]
"""
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=GROQ_MODEL,
            temperature=0.2,
            max_tokens=250
        )
        
        content = chat_completion.choices[0].message.content.strip()
        # Clean potential markdown JSON syntax
        if "```" in content:
            content = re.sub(r'```json|```', '', content).strip()
            
        start_idx = content.find('[')
        end_idx = content.rfind(']')
        if start_idx != -1 and end_idx != -1:
            json_str = content[start_idx:end_idx + 1]
            keywords = json.loads(json_str)
            if isinstance(keywords, list) and len(keywords) > 0:
                print(f"[Query Strategist] Suggested {len(keywords)} keywords: {keywords}")
                db_client.insert_keywords(keywords)
                return keywords
                
    except Exception as e:
        print(f"[Query Strategist] Groq API call failed: {e}. Falling back to default list.")
        
    db_client.insert_keywords(DEFAULT_KEYWORDS)
    return DEFAULT_KEYWORDS
