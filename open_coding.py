import os
import json
from dotenv import load_dotenv

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

# Default static fallback themes for Blinkit category exploration
DEFAULT_OPEN_CODING_THEMES = [
    "Vegetables Out-of-Stock: Users report that organic veggies are frequently unavailable.",
    "Reorder Convenience: Users praise the 1-click reorder widget for fresh produce.",
    "Cluttered Sub-Menus: Complaints about finding baby care or gourmet items hidden under submenus.",
    "Substitutes Forcing: Frustration when the app forces substitutes on out-of-stock items instead of letting them browse alternatives.",
    "Stale Recommendations: Users feel the homepage recommendation strip never refreshes with new categories.",
    "Search vs Browse: Users prefer using the search bar because category browse navigation is too slow and cluttered.",
    "Delivery Fees on Categories: Complaints about delivery charges varying across different grocery categories."
]

def run_open_coding(sample_records):
    """
    Open Coding Agent:
    Performs unconstrained theme extraction on 200-300 records to identify user behaviors and pain points.
    """
    print(f"[Open Coding] Running theme extraction on {len(sample_records)} records...")
    
    if not sample_records:
        return DEFAULT_OPEN_CODING_THEMES
        
    if not GROQ_API_KEY:
        print("[Open Coding] Groq API key missing. Using static open coding fallbacks.")
        return DEFAULT_OPEN_CODING_THEMES

    texts = [r["text"] for r in sample_records[:300]]
    prompt = f"""
You are a qualitative research analyst. Analyze this batch of user feedback from a quick-commerce grocery delivery app (Blinkit).
Extract a free-form list of themes, user pain points, and specific behaviors related to category discovery, browse navigation, recommendation widgets, reordering habits, and search interactions.

User feedback sample:
{json.dumps(texts, indent=2)}

Provide a list of 10-15 descriptive themes, each with a brief 1-sentence description of the user issue/praise.
Output ONLY a valid JSON list of strings (e.g. ["Theme 1: description", "Theme 2: description"]). Do not write conversational text or markdown blocks.
"""
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY, timeout=6.0)
        
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=GROQ_MODEL,
            temperature=0.2,
            max_tokens=500
        )
        
        content = chat_completion.choices[0].message.content.strip()
        if "```" in content:
            content = re.sub(r'```json|```', '', content).strip()
            
        import re
        start_idx = content.find('[')
        end_idx = content.rfind(']')
        if start_idx != -1 and end_idx != -1:
            json_str = content[start_idx:end_idx + 1]
            themes = json.loads(json_str)
            if isinstance(themes, list) and len(themes) > 0:
                print(f"[Open Coding] Extracted {len(themes)} themes successfully.")
                return themes
                
    except Exception as e:
        print(f"[Open Coding] Groq API call failed: {e}. Using static open coding fallbacks.")
        
    return DEFAULT_OPEN_CODING_THEMES
