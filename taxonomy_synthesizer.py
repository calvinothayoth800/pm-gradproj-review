import os
import json
import re
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

TAXONOMY_FILE = "taxonomy_proposal.json"

DEFAULT_TAXONOMY = {
    "approved": False,
    "categories": [
        {
            "name": "Fresh Produce Out-Of-Stock",
            "description": "User experiences issues finding fresh vegetables or fruits in stock in their local delivery radius.",
            "examples": [
                "Blinkit category recommendations are so bad. I only buy vegetables but it keeps showing pet food.",
                "Blinkit keeps recommending items that are out of stock in my area. Why explore new categories then?"
            ]
        },
        {
            "name": "Reorder Widget Convenience",
            "description": "User highlights positive experiences or speed improvements using the 1-click reorder produce features.",
            "examples": [
                "I love the 'reorder' widget on Blinkit! Makes buying my weekly vegetables in 1 click so easy."
            ]
        },
        {
            "name": "Category Browse Clutter",
            "description": "User expresses frustration with hard-to-navigate category layouts, submenus, or buried items.",
            "examples": [
                "The category browse layout is cluttered. Cannot find organic milk easily on this app update.",
                "Beautiful new UI in Blinkit, but why did they hide the 'Fresh Produce' category under submenus?"
            ]
        },
        {
            "name": "Forced Substitutes",
            "description": "Frustrations when the system suggests or forces replacements for out-of-stock items instead of category browsing.",
            "examples": [
                "The app keeps forcing substitutes when items are out of stock instead of letting me browse similar categories."
            ]
        },
        {
            "name": "Stale recommendations",
            "description": "Home recommendation strips or 'never tried' carousels remain static and don't match active interest.",
            "examples": [
                "Every time I open the app, it shows 'never tried' categories which I don't care about.",
                "Blinkit delivery is fast but the category recommendation algorithm is stale. Same old suggestions."
            ]
        },
        {
            "name": "Search Preference",
            "description": "Users prefer using direct text searches because catalog category browsing is sluggish or broken.",
            "examples": [
                "The search feature works well, but category-based navigation is cluttered and broken."
            ]
        }
    ]
}

def run_taxonomy_synthesis(open_coding_themes, raw_feedback_sample):
    """
    Taxonomy Synthesizer Agent:
    Clusters open coding themes into 6-10 finalized categories with definitions and quotes.
    Saves to taxonomy_proposal.json for user approval.
    """
    print("[Taxonomy Synthesizer] Clustering themes to build category taxonomy...")
    
    if not GROQ_API_KEY:
        print("[Taxonomy Synthesizer] Groq API key missing. Generating default offline taxonomy proposal.")
        save_taxonomy_proposal(DEFAULT_TAXONOMY)
        return DEFAULT_TAXONOMY

    prompt = f"""
You are a Lead Product Researcher and AI Architect. Analyze these user open coding themes:
{json.dumps(open_coding_themes, indent=2)}

Also look at a few examples of raw user reviews:
{json.dumps([r["text"] for r in raw_feedback_sample[:20]], indent=2)}

Group these themes into 6 to 10 distinct, clean categories representing product pain points, user cohorts, or usability achievements.
For each category, provide:
1. name: A short CamelCase or simple title (e.g. "CategoryBrowseClutter", "ReorderWidgetPerformance").
2. description: A clear definition of when a review belongs to this category.
3. examples: A list of 1-2 exact or paraphrased sample quotes representing this behavior.

Output ONLY a valid JSON object matching this structure:
{{
  "approved": false,
  "categories": [
    {{
      "name": "CategoryName",
      "description": "Definition",
      "examples": ["quote1", "quote2"]
    }}
  ]
}}
Do not write conversational text or markdown blocks.
"""
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY, timeout=6.0)
        
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=GROQ_MODEL,
            temperature=0.2,
            max_tokens=600
        )
        
        content = chat_completion.choices[0].message.content.strip()
        if "```" in content:
            content = re.sub(r'```json|```', '', content).strip()
            
        start_idx = content.find('{')
        end_idx = content.rfind('}')
        if start_idx != -1 and end_idx != -1:
            json_str = content[start_idx:end_idx + 1]
            proposal = json.loads(json_str)
            
            # Reset approved flag to false for checkpoint
            proposal["approved"] = False
            
            save_taxonomy_proposal(proposal)
            return proposal
            
    except Exception as e:
        print(f"[Taxonomy Synthesizer] Groq API call failed: {e}. Writing default fallback taxonomy.")
        
    save_taxonomy_proposal(DEFAULT_TAXONOMY)
    return DEFAULT_TAXONOMY

def save_taxonomy_proposal(taxonomy):
    """Save proposal to taxonomy_proposal.json."""
    with open(TAXONOMY_FILE, "w") as f:
        json.dump(taxonomy, f, indent=2)
    print(f"[Taxonomy Synthesizer] Saved taxonomy proposal to '{TAXONOMY_FILE}'. Pipeline is now waiting for user approval.")

def load_taxonomy_proposal():
    """Load proposal from taxonomy_proposal.json if it exists."""
    if os.path.exists(TAXONOMY_FILE):
        try:
            with open(TAXONOMY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return None
    return None
