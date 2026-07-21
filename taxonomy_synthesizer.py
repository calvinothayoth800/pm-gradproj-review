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
    "approved": True,
    "categories": [
        {
            "name": "Habit_Loop_Repetitive_Buying",
            "description": "User buys the same daily/weekly items repeatedly and uses Blinkit purely as a routine utility, ignoring other categories.",
            "mapped_unmet_need": "N1: Habitual Blinders & Intent-Only Shopping",
            "examples": [
                "I only buy milk and eggs on Blinkit every morning. Never browse anything else.",
                "Opened app just for bread as usual. Didn't see any other sections."
            ]
        },
        {
            "name": "Trust_Quality_Barrier_Non_Grocery",
            "description": "User doubts product authenticity, freshness, return policies, or quality for high-value/non-grocery categories (Electronics, Beauty, Pet Care, Baby Care).",
            "mapped_unmet_need": "N2: High Perceived Risk in Non-Grocery Categories",
            "examples": [
                "Wont buy headphones or cosmetics on 10 min delivery. What if it's fake or damaged?",
                "Don't trust buying electronics here. Prefer Amazon for proper warranty."
            ]
        },
        {
            "name": "Search_Only_Bypass",
            "description": "User relies exclusively on the direct search bar to buy specific items and completely bypasses category browsing, home feeds, or curated widgets.",
            "mapped_unmet_need": "N1: Habitual Blinders & Intent-Only Shopping",
            "examples": [
                "I just type what I want in the search bar, buy it, and close the app.",
                "Search bar is the only thing I use. Category icons are too cluttered."
            ]
        },
        {
            "name": "Price_Value_Trial_Hesitation",
            "description": "User feels non-grocery items are overpriced, lack trial discounts, or lack bundle incentives compared to specialized platforms (Amazon/Nykaa).",
            "mapped_unmet_need": "N3: Absence of Contextual Discovery & Trial Incentives",
            "examples": [
                "Non-grocery items are expensive without any sample discounts.",
                "Why would I buy beauty products here without Nykaa discounts?"
            ]
        },
        {
            "name": "UI_Category_Visibility_Clutter",
            "description": "User complains that non-grocery categories are hidden, hard to navigate, or overwhelmed by crowded promotional banners.",
            "mapped_unmet_need": "N3: Absence of Contextual Discovery & Trial Incentives",
            "examples": [
                "App UI is so crowded with banners. Can't find where pet care category is.",
                "Category navigation is buried under multiple submenus."
            ]
        },
        {
            "name": "Successful_Category_Exploration",
            "description": "Positive feedback where user successfully discovered and purchased from a new non-grocery category.",
            "mapped_unmet_need": "Positive Reinforcement",
            "examples": [
                "Glad I discovered pet toys on Blinkit! Delivered in 10 mins.",
                "Tried buying skin care for the first time here and loved the experience."
            ]
        },
        {
            "name": "Out_Of_Scope_Operations",
            "description": "Generic logistics, late delivery, rider behavior, missing items, damaged packaging, or customer support refund complaints.",
            "mapped_unmet_need": "Operational Noise (Filtered Out)",
            "examples": [
                "Rider was late by 30 mins.",
                "Bad customer support. Refund not processed for rotten mangoes."
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
