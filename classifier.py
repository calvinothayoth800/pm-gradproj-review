import os
import json
import time
import re
from dotenv import load_dotenv
from groq import Groq
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

MICRO_THEME_MAP = {
    "ClutteredCategoryBrowse": "UI_Category_Visibility_Clutter",
    "PoorNavigation": "UI_Category_Visibility_Clutter",
    "IrrelevantRecommendations": "Habit_Loop_Repetitive_Buying",
    "StaleCategoryRecommendations": "Habit_Loop_Repetitive_Buying",
    "ReorderWidgetPerformance": "Habit_Loop_Repetitive_Buying",
    "OutOfStockRecommendations": "Habit_Loop_Repetitive_Buying",
    "ForcedSubstitutes": "Habit_Loop_Repetitive_Buying"
}

# Fuzzy match LLM outputs to active category list
def match_closest_category(output_theme, categories):
    if not output_theme:
        return categories[0] if categories else "Out_Of_Scope_Operations"
        
    str_theme = str(output_theme).strip()
    
    # Mandatory micro-theme reconciliation mapping
    if str_theme in MICRO_THEME_MAP:
        return MICRO_THEME_MAP[str_theme]
        
    if not categories:
        return "Out_Of_Scope_Operations"
        
    if str_theme in categories:
        return str_theme
        
    clean_output = re.sub(r'[^a-zA-Z0-9]', '', str_theme).lower()
    for cat in categories:
        clean_cat = re.sub(r'[^a-zA-Z0-9]', '', str(cat)).lower()
        if clean_output == clean_cat or clean_output in clean_cat or clean_cat in clean_output:
            return cat
            
    # Check if a category matches the best overlap word
    words = clean_output.split()
    for word in words:
        if len(word) > 3:
            for cat in categories:
                if word in cat.lower():
                    return cat
                    
    return categories[0]

# Default local rule based classifier for Blinkit category exploration
def rule_based_fallback(text, categories):
    """Local semantic rule-based classifier when Groq is unavailable."""
    text_lower = text.lower()
    
    theme = None
    sentiment = "Disappointed"
    user_cohort = "Unspecified_Insufficient_Context"
    root_cause = "General user feedback on app features"
    is_discovery_relevant = True
    
    # 1. Operational & Logistics Out of Scope Noise
    if any(w in text_lower for w in ["late", "delay", "rider", "delivery boy", "refund", "rotten", "damaged", "defected", "customer service", "bad service", "handling charge", "extra fee"]):
        theme = next((c for c in categories if "Out_Of_Scope" in c or "Operations" in c or "Out-Of-Stock" in c), "Out_Of_Scope_Operations")
        sentiment = "Highly Frustrated"
        root_cause = "Operational delivery delay or customer support dispute"
        is_discovery_relevant = False
    elif any(w in text_lower for w in ["search", "type", "direct search", "search bar", "find"]):
        theme = next((c for c in categories if "Search" in c or "search" in c.lower()), "Search_Only_Bypass")
        sentiment = "Negative"
        root_cause = "Uses direct search bar exclusively to bypass category browsing"
        user_cohort = "Single_Category_Shopper"
    elif any(w in text_lower for w in ["reorder", "widget", "1-click", "routine", "daily", "milk", "eggs", "every morning"]):
        theme = next((c for c in categories if "Habit" in c or "Reorder" in c or "reorder" in c.lower()), "Habit_Loop_Repetitive_Buying")
        sentiment = "Positive" if "reorder" in text_lower or "love" in text_lower else "Disappointed"
        root_cause = "Buys routine daily essentials repeatedly, ignoring non-grocery categories"
        user_cohort = "Power_Grocery_Shopper"
    elif any(w in text_lower for w in ["clutter", "design", "layout", "menu", "submenu", "navigation", "buried", "banner"]):
        theme = next((c for c in categories if "UI" in c or "Clutter" in c or "Browse" in c), "UI_Category_Visibility_Clutter")
        sentiment = "Negative"
        root_cause = "Crowded UI banners and deep submenus obscure non-grocery sections"
    elif any(w in text_lower for w in ["expensive", "price", "cost", "discount", "nykaa", "amazon", "overpriced"]):
        theme = next((c for c in categories if "Price" in c or "price" in c.lower()), "Price_Value_Trial_Hesitation")
        sentiment = "Disappointed"
        root_cause = "Unwilling to test non-grocery categories without trial incentives"
    elif any(w in text_lower for w in ["fake", "quality", "warranty", "electronics", "headphones", "cosmetics", "trust"]):
        theme = next((c for c in categories if "Trust" in c or "Quality" in c), "Trust_Quality_Barrier_Non_Grocery")
        sentiment = "Highly Frustrated"
        root_cause = "Doubts authenticity and warranty for high-value non-grocery categories"
        user_cohort = "Category_Explorer"
    elif any(w in text_lower for w in ["discovered", "first time", "tried", "love finding", "pet toys"]):
        theme = next((c for c in categories if "Successful" in c or "Exploration" in c), "Successful_Category_Exploration")
        sentiment = "Positive"
        root_cause = "Successfully discovered and bought non-grocery items"
        user_cohort = "Category_Explorer"

    if not theme:
        # Default fallback to Out_Of_Scope if generic short noise
        theme = next((c for c in categories if "Out_Of_Scope" in c), categories[0] if categories else "Out_Of_Scope_Operations")
        if "Out_Of_Scope" in theme:
            is_discovery_relevant = False

    # Sentiment overrides
    if any(w in text_lower for w in ["love", "great", "excellent", "fast", "convenient", "amazing"]):
        sentiment = "Positive"
    elif any(w in text_lower for w in ["worst", "hate", "terrible", "useless", "uninstall", "fraud"]):
        sentiment = "Highly Frustrated"

    return {
        "theme": theme,
        "sentiment": sentiment,
        "user_type": user_cohort,
        "root_cause": root_cause[:150],
        "confidence_score": 4 if theme else 3,
        "is_discovery_relevant": is_discovery_relevant
    }

def create_groq_completion(client, messages, response_format=None, max_tokens=200):
    """Call Groq API with automatic model fallback for rate limits / token exhausts."""
    last_error = None
    models = [GROQ_MODEL] if GROQ_MODEL not in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it", "mixtral-8x7b-32768"] else []
    models += ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it", "mixtral-8x7b-32768"]
    
    # Deduplicate list
    seen = set()
    dedup_models = [m for m in models if not (m in seen or seen.add(m))]
    
    for model in dedup_models:
        try:
            kwargs = {
                "messages": messages,
                "model": model,
                "temperature": 0.1,
                "max_tokens": max_tokens
            }
            if response_format:
                kwargs["response_format"] = response_format
                
            chat_completion = client.chat.completions.create(**kwargs)
            return chat_completion.choices[0].message.content.strip()
        except Exception as e:
            err_str = str(e)
            if "rate_limit_exceeded" in err_str or "429" in err_str:
                print(f"[Classifier] Model {model} hit rate limit / token exhaust. Trying fallback model...")
                last_error = e
                continue
            else:
                raise e
    raise last_error

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

def classify_review(text, categories, raise_on_error=False):
    """
    Classifier Agent:
    Uses Groq JSON mode to classify a raw review text against the active PM Category Discovery taxonomy.
    """
    if not GROQ_API_KEY:
        return rule_based_fallback(text, categories)
        
    allowed_sentiments = ["Positive", "Disappointed", "Highly Frustrated", "Neutral"]
    allowed_cohorts = ["Power_Grocery_Shopper", "Category_Explorer", "Single_Category_Shopper", "Unspecified_Insufficient_Context"]
    
    prompt = f"""
You are an expert Principal Product Manager on Blinkit's Growth Team specializing in Category Discovery and User Shopping Behavior.
Analyze this customer review:
"{text}"

CRITICAL PROCESSING RULES:
1. Deduplication & Clean-up: Ignore test records or generic phrases like "good app" or "fast delivery".
2. Out-of-Scope Filtering: If a review is strictly about rider delays, damaged products, or refund processing, classify Theme as "Out_Of_Scope_Operations" and Confidence Score as 5.
3. User Cohort Strictness: DO NOT classify a user as "Power_Grocery_Shopper" or "Category_Explorer" unless explicit behavioral evidence exists in the text. Otherwise, output "Unspecified_Insufficient_Context".
4. Root Cause Extraction: Extract a succinct 3-7 word first-principles root cause (e.g., "Prefers Amazon for electronic warranties", "Uses app solely for emergency milk").

Allowed PM Taxonomy Categories:
{json.dumps(categories, indent=2)}

Allowed Sentiment Enums: {allowed_sentiments}
Allowed User Cohort Enums: {allowed_cohorts}

Output a JSON object with these EXACT keys:
- "sentiment_severity": Choose one from Allowed Sentiment Enums.
- "user_cohort": Choose one from Allowed User Cohort Enums.
- "pain_point_category": Choose one of the category names from the taxonomy list above.
- "root_cause_description": A specific 3-to-7 word PM first-principles root cause.
- "confidence_score": An integer from 1 to 5 indicating your classification confidence.

Example format:
{{
  "sentiment_severity": "Disappointed",
  "user_cohort": "Unspecified_Insufficient_Context",
  "pain_point_category": "UI_Category_Visibility_Clutter",
  "root_cause_description": "Nested submenus hide gourmet items",
  "confidence_score": 5
}}

Provide ONLY raw JSON. No conversational text or markdown blocks.
"""
    try:
        client = Groq(api_key=GROQ_API_KEY, timeout=6.0)
        response_text = create_groq_completion(
            client=client,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=200
        )
        result = clean_llm_json(response_text)
        
        if result:
            theme = result.get("pain_point_category")
            theme = match_closest_category(theme, categories)
                
            sentiment = result.get("sentiment_severity")
            if sentiment not in allowed_sentiments:
                sentiment = "Disappointed"
                
            cohort = result.get("user_cohort")
            if cohort not in allowed_cohorts:
                cohort = "Unspecified_Insufficient_Context"
                
            confidence = result.get("confidence_score")
            try:
                confidence = int(confidence)
            except Exception:
                confidence = 4
                
            is_relevant = theme != "Out_Of_Scope_Operations"
            
            return {
                "theme": theme,
                "sentiment": sentiment,
                "user_type": cohort,
                "root_cause": result.get("root_cause_description", "Category exploration barrier")[:150],
                "confidence_score": confidence,
                "is_discovery_relevant": is_relevant
            }
            
    except Exception as e:
        print(f"[Classifier] Groq API call failed: {e}.")
        if raise_on_error:
            raise e
        print("Falling back to rules.")
        
    return rule_based_fallback(text, categories)

def classify_reviews_batch(reviews_list, categories):
    """
    Classify a batch of reviews in a single Groq LLM request using NextLeap PM Discovery rules.
    """
    if not GROQ_API_KEY:
        results = []
        for r in reviews_list:
            res = rule_based_fallback(r["text"], categories)
            res["review_id"] = r["review_id"]
            res["text"] = r["text"]
            results.append(res)
        return results
        
    client = Groq(api_key=GROQ_API_KEY, timeout=6.0)
    
    allowed_sentiments = ["Positive", "Disappointed", "Highly Frustrated", "Neutral"]
    allowed_cohorts = ["Power_Grocery_Shopper", "Category_Explorer", "Single_Category_Shopper", "Unspecified_Insufficient_Context"]
    
    input_reviews = [{"id": r["review_id"], "text": r["text"]} for r in reviews_list]
    
    prompt = f"""
You are an expert Principal Product Manager on Blinkit's Growth Team specializing in Category Discovery and User Shopping Behavior.
Classify the following customer reviews against the PM Category Discovery Taxonomy.

CRITICAL PROCESSING RULES:
1. Deduplication & Clean-up: Ignore test records or generic phrases like "good app" or "fast delivery".
2. Out-of-Scope Filtering: If a review is strictly about rider delays, damaged products, or refund processing, classify Theme as "Out_Of_Scope_Operations" and Confidence Score as 5.
3. User Cohort Strictness: DO NOT classify a user as "Power_Grocery_Shopper" or "Category_Explorer" unless explicit behavioral evidence exists in the text. Otherwise, output "Unspecified_Insufficient_Context".
4. Root Cause Extraction: Extract a succinct 3-7 word first-principles root cause (e.g., "Prefers Amazon for electronic warranties", "Uses app solely for emergency milk").

Allowed PM Taxonomy Categories: {json.dumps(categories)}
Allowed Sentiment Enums: {allowed_sentiments}
Allowed User Cohort Enums: {allowed_cohorts}

List of reviews to classify:
{json.dumps(input_reviews, indent=2)}

Output a single JSON object containing a "classifications" array, where each element has these EXACT keys:
- "review_id": The exact review ID from the input list.
- "sentiment_severity": Choose one from Allowed Sentiment Enums.
- "user_cohort": Choose one from Allowed User Cohort Enums.
- "pain_point_category": Choose one category name from the Allowed PM Taxonomy Categories.
- "root_cause_description": A succinct 3-to-7 word PM first-principles root cause.
- "confidence_score": An integer from 1 to 5 indicating your classification confidence.

Provide ONLY raw JSON. No conversational text or markdown blocks. Do not wrap in backticks or markdown JSON codeblocks.
"""
    try:
        response_text = create_groq_completion(
            client=client,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=1500
        )
        data = clean_llm_json(response_text)
        
        if data and "classifications" in data:
            results = []
            id_to_review = {r["review_id"]: r for r in reviews_list}
            for c in data["classifications"]:
                review_id = c.get("review_id")
                if review_id not in id_to_review:
                    continue
                    
                theme = c.get("pain_point_category")
                theme = match_closest_category(theme, categories)
                    
                sentiment = c.get("sentiment_severity")
                if sentiment not in allowed_sentiments:
                    sentiment = "Disappointed"
                    
                cohort = c.get("user_cohort")
                if cohort not in allowed_cohorts:
                    cohort = "Unspecified_Insufficient_Context"
                    
                confidence = c.get("confidence_score")
                try:
                    confidence = int(confidence)
                except Exception:
                    confidence = 4
                    
                is_relevant = theme != "Out_Of_Scope_Operations"
                    
                results.append({
                    "review_id": review_id,
                    "text": id_to_review[review_id]["text"],
                    "theme": theme,
                    "sentiment": sentiment,
                    "user_type": cohort,
                    "root_cause": c.get("root_cause_description", "Category exploration barrier")[:150],
                    "confidence_score": confidence,
                    "is_discovery_relevant": is_relevant
                })
            return results
    except Exception as e:
        print(f"[Classifier] Batch classification failed: {e}. Retrying items individually via LLM...")
        
        results = []
        for r in reviews_list:
            try:
                res = classify_review(r["text"], categories, raise_on_error=True)
                res["review_id"] = r["review_id"]
                res["text"] = r["text"]
                results.append(res)
            except Exception as e_single:
                print(f"[Classifier] Individual LLM retry failed for review {r['review_id']}: {e_single}. Flagging as AI failure.")
                results.append({
                    "review_id": r["review_id"],
                    "text": r["text"],
                    "theme": "Ineligible / AI Failure",
                    "sentiment": "Negative",
                    "user_type": "Unspecified_Insufficient_Context",
                    "root_cause": f"AI Failure: {str(e_single)[:100]}",
                    "confidence_score": 1,
                    "spot_checked": True,
                    "spot_check_valid": None,
                    "is_discovery_relevant": False
                })
        return results
