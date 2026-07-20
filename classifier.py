import os
import json
import time
import re
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

# Default local rule based classifier for Blinkit category exploration
def rule_based_fallback(text, categories):
    """Local regex fallback classifier when Groq is unavailable."""
    text_lower = text.lower()
    
    # Defaults
    theme = categories[0] if categories else "Fresh Produce Out-Of-Stock"
    sentiment = "Disappointed"
    user_cohort = "Casual Listener"  # Default fallback cohort, we will map to grocery terms: Casual Shopper
    root_cause = "Item or category could not be explored"
    confidence = 3
    
    # Simple regex mapping
    if any(w in text_lower for w in ["stock", "unavailable", "empty", "no veggies", "no fruits"]):
        theme = next((c for c in categories if "Stock" in c or "stock" in c.lower()), theme)
        sentiment = "Highly Frustrated"
        root_cause = "Fresh produce categories frequently show out of stock items"
    elif any(w in text_lower for w in ["reorder", "widget", "1-click", "re-order"]):
        theme = next((c for c in categories if "Reorder" in c or "reorder" in c.lower()), theme)
        sentiment = "Positive"
        root_cause = "Successful use of 1-click reorder shortcut"
        user_cohort = "Power User"
    elif any(w in text_lower for w in ["clutter", "design", "layout", "menu", "submenu", "navigation"]):
        theme = next((c for c in categories if "Clutter" in c or "Browse" in c or "browse" in c.lower()), theme)
        sentiment = "Negative"
        root_cause = "Deep nested submenus and cluttered interface slow down category exploration"
    elif any(w in text_lower for w in ["substitute", "force", "replace"]):
        theme = next((c for c in categories if "Substitute" in c or "substitute" in c.lower()), theme)
        sentiment = "Highly Frustrated"
        root_cause = "App forces item substitutions instead of category alternatives"
    elif any(w in text_lower for w in ["recommend", "recommendation", "stale", "carousel", "never tried"]):
        theme = next((c for c in categories if "recommend" in c.lower() or "stale" in c.lower()), theme)
        sentiment = "Negative"
        root_cause = "Category recommendations do not refresh or adapt to user profile"
    elif any(w in text_lower for w in ["search", "type", "find"]):
        theme = next((c for c in categories if "Search" in c or "search" in c.lower()), theme)
        sentiment = "Negative"
        root_cause = "Browse is slow, prompting user to search directly"

    # Map general sentiment terms
    if any(w in text_lower for w in ["love", "great", "excellent", "fast", "convenient"]):
        sentiment = "Positive"
    elif any(w in text_lower for w in ["hate", "worst", "terrible", "useless", "uninstall"]):
        sentiment = "Highly Frustrated"
        
    # Map general cohorts
    if any(w in text_lower for w in ["weekly", "every day", "daily", "always"]):
        user_cohort = "Power User"
    elif any(w in text_lower for w in ["first time", "tried", "new"]):
        user_cohort = "New Shopper"
    else:
        user_cohort = "Casual Shopper"

    return {
        "theme": theme,
        "sentiment": sentiment,
        "user_type": user_cohort,
        "root_cause": root_cause,
        "confidence_score": confidence
    }

def clean_llm_json(response_text):
    """Safely extract valid JSON content within outermost braces."""
    try:
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        if start_idx == -1 or end_idx == -1:
            return None
        json_str = response_text[start_idx:end_idx + 1]
        return json.loads(json_str)
    except Exception:
        return None

def classify_review(text, categories):
    """
    Classifier Agent:
    Uses Groq JSON mode to classify a raw review text against the active taxonomy.
    """
    if not GROQ_API_KEY:
        return rule_based_fallback(text, categories)
        
    from groq import Groq
    
    # Prompt outlining taxonomy and enums
    allowed_sentiments = ["Positive", "Negative", "Disappointed", "Highly Frustrated"]
    allowed_cohorts = ["Power User", "Casual Shopper", "New Shopper", "Organic Shopper"]
    
    prompt = f"""
You are a Growth PM and Data Architect analyzing category exploration and discovery on the grocery app Blinkit.
Analyze this review:
"{text}"

Classify it using this taxonomy (choose the closest matching category):
{json.dumps(categories, indent=2)}

Allowed Sentiment Enums: {allowed_sentiments}
Allowed User Cohort Enums: {allowed_cohorts}

Output a JSON object with these EXACT keys:
- "sentiment_severity": Choose one from Allowed Sentiment Enums.
- "user_cohort": Choose one from Allowed User Cohort Enums.
- "pain_point_category": Choose one of the category names from the taxonomy list above.
- "root_cause_description": A specific 5-to-7 word description of the specific issue/success.
- "confidence_score": An integer from 1 to 5 indicating your classification confidence.

Example format:
{{
  "sentiment_severity": "Disappointed",
  "user_cohort": "Casual Shopper",
  "pain_point_category": "CategoryBrowseClutter",
  "root_cause_description": "Nested submenus hide gourmet items",
  "confidence_score": 5
}}

Provide ONLY raw JSON. No conversational text or markdown blocks.
"""
    try:
        client = Groq(api_key=GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=GROQ_MODEL,
            temperature=0.1,
            # Native JSON Mode enforcement
            response_format={"type": "json_object"},
            max_tokens=200
        )
        
        response_text = chat_completion.choices[0].message.content.strip()
        result = clean_llm_json(response_text)
        
        if result:
            # Validate output fields and fallbacks
            theme = result.get("pain_point_category")
            if theme not in categories:
                # Default to closest match or first category
                result["pain_point_category"] = categories[0] if categories else "Fresh Produce Out-Of-Stock"
                
            sentiment = result.get("sentiment_severity")
            if sentiment not in allowed_sentiments:
                result["sentiment_severity"] = "Negative"
                
            cohort = result.get("user_cohort")
            if cohort not in allowed_cohorts:
                result["user_cohort"] = "Casual Shopper"
                
            confidence = result.get("confidence_score")
            try:
                result["confidence_score"] = int(confidence)
            except Exception:
                result["confidence_score"] = 4
                
            # Remap fields to match DB columns (theme, sentiment, user_type, root_cause, confidence_score)
            return {
                "theme": result["pain_point_category"],
                "sentiment": result["sentiment_severity"],
                "user_type": result["user_cohort"],
                "root_cause": result.get("root_cause_description", "Item could not be explored"),
                "confidence_score": result["confidence_score"]
            }
            
    except Exception as e:
        print(f"[Classifier] Groq API call failed: {e}. Falling back to rules.")
        
    return rule_based_fallback(text, categories)

def classify_reviews_batch(reviews_list, categories):
    """
    Classify a batch of reviews (up to 15) in a single Groq LLM request to speed up classification 10x.
    """
    if not GROQ_API_KEY:
        results = []
        for r in reviews_list:
            res = rule_based_fallback(r["text"], categories)
            res["review_id"] = r["review_id"]
            res["text"] = r["text"]
            results.append(res)
        return results
        
    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)
    
    allowed_sentiments = ["Positive", "Negative", "Disappointed", "Highly Frustrated"]
    allowed_cohorts = ["Power User", "Casual Shopper", "New Shopper", "Organic Shopper"]
    
    input_reviews = [{"id": r["review_id"], "text": r["text"]} for r in reviews_list]
    
    prompt = f"""
You are a Growth PM and Data Architect analyzing category exploration and discovery on the grocery app Blinkit.
Classify the following list of customer reviews against the active taxonomy.

Allowed Taxonomy Categories: {json.dumps(categories)}
Allowed Sentiment Enums: {allowed_sentiments}
Allowed User Cohort Enums: {allowed_cohorts}

List of reviews to classify:
{json.dumps(input_reviews, indent=2)}

Output a single JSON object containing a "classifications" array, where each element corresponds to a review and has these EXACT keys:
- "review_id": The exact review ID from the input list.
- "sentiment_severity": Choose one from Allowed Sentiment Enums.
- "user_cohort": Choose one from Allowed User Cohort Enums.
- "pain_point_category": Choose one category name from the Allowed Taxonomy Categories.
- "root_cause_description": A specific 5-to-7 word description of the specific issue/success.
- "confidence_score": An integer from 1 to 5 indicating your classification confidence.

Provide ONLY raw JSON. No conversational text or markdown blocks. Do not wrap in backticks or markdown JSON codeblocks.
"""
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=GROQ_MODEL,
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=1500
        )
        
        response_text = chat_completion.choices[0].message.content.strip()
        data = clean_llm_json(response_text)
        
        if data and "classifications" in data:
            results = []
            id_to_review = {r["review_id"]: r for r in reviews_list}
            for c in data["classifications"]:
                review_id = c.get("review_id")
                if review_id not in id_to_review:
                    continue
                    
                theme = c.get("pain_point_category")
                if theme not in categories:
                    theme = categories[0] if categories else "Fresh Produce Out-Of-Stock"
                    
                sentiment = c.get("sentiment_severity")
                if sentiment not in allowed_sentiments:
                    sentiment = "Negative"
                    
                cohort = c.get("user_cohort")
                if cohort not in allowed_cohorts:
                    cohort = "Casual Shopper"
                    
                confidence = c.get("confidence_score")
                try:
                    confidence = int(confidence)
                except Exception:
                    confidence = 4
                    
                results.append({
                    "review_id": review_id,
                    "text": id_to_review[review_id]["text"],
                    "theme": theme,
                    "sentiment": sentiment,
                    "user_type": cohort,
                    "root_cause": c.get("root_cause_description", "Item could not be explored"),
                    "confidence_score": confidence
                })
            return results
    except Exception as e:
        print(f"[Classifier] Batch classification failed: {e}. Falling back to single-item classification.")
        
    results = []
    for r in reviews_list:
        res = classify_review(r["text"], categories)
        res["review_id"] = r["review_id"]
        res["text"] = r["text"]
        results.append(res)
        time.sleep(1.0)
    return results
