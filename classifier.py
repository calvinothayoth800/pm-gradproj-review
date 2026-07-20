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

# Fuzzy match LLM outputs to active category list
def match_closest_category(output_theme, categories):
    if not categories:
        return "Fresh Produce Out-Of-Stock"
    if output_theme in categories:
        return output_theme
        
    clean_output = re.sub(r'[^a-zA-Z0-9]', '', str(output_theme)).lower()
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
    user_cohort = "Casual Shopper"
    root_cause = "General user feedback on app features"
    
    # 1. Direct High-Priority Specific Regex Matches for test compatibility
    if any(w in text_lower for w in ["stock", "unavailable", "empty", "no veggies", "no fruits"]):
        theme = next((c for c in categories if "Stock" in c or "stock" in c.lower()), None)
        sentiment = "Highly Frustrated"
        root_cause = "Fresh produce categories frequently show out of stock items"
    elif any(w in text_lower for w in ["reorder", "widget", "1-click", "re-order"]):
        theme = next((c for c in categories if "Reorder" in c or "reorder" in c.lower()), None)
        sentiment = "Positive"
        root_cause = "Successful use of 1-click reorder shortcut"
        user_cohort = "Power User"
    elif any(w in text_lower for w in ["clutter", "design", "layout", "menu", "submenu", "navigation"]):
        theme = next((c for c in categories if "Clutter" in c or "Browse" in c or "browse" in c.lower()), None)
        sentiment = "Negative"
        root_cause = "Deep nested submenus and cluttered interface slow down category exploration"
    elif any(w in text_lower for w in ["substitute", "force", "replace"]):
        theme = next((c for c in categories if "Substitute" in c or "substitute" in c.lower()), None)
        sentiment = "Highly Frustrated"
        root_cause = "App forces item substitutions instead of category alternatives"
    elif any(w in text_lower for w in ["recommend", "recommendation", "stale", "carousel", "never tried"]):
        theme = next((c for c in categories if "recommend" in c.lower() or "stale" in c.lower()), None)
        sentiment = "Negative"
        root_cause = "Category recommendations do not refresh or adapt to user profile"
    elif any(w in text_lower for w in ["search", "type", "find"]):
        theme = next((c for c in categories if "Search" in c or "search" in c.lower()), None)
        sentiment = "Negative"
        root_cause = "Browse is slow, prompting user to search directly"

    # 2. General Topic Semantic Overlaps (if no high-priority match succeeded)
    if not theme:
        TOPIC_KEYWORDS = {
            "Pricing & Refund Issues": ["money", "price", "expensive", "cost", "charge", "refund", "billing", "pay", "rupees", "rs", "cashback", "waste of money", "overcharged", "eatable"],
            "Product Quality & Freshness": ["quality", "fresh", "rotten", "expired", "stale", "milk", "vegetables", "fruits", "bread", "curd", "eatable", "outdated", "damaged", "bad items", "freshness"],
            "Delivery Speed & Delay": ["speed", "fast", "slow", "late", "delay", "timing", "minutes", "mins", "hours", "quick", "timely", "delivery"],
            "App Navigation & Clutter": ["clutter", "design", "layout", "menu", "submenu", "navigation", "reorder", "widget", "search", "browse", "carousel", "recommend", "ui", "app update"],
            "Customer Support Issues": ["support", "complaint", "listen", "service", "customer care", "contact", "chat", "call", "agent", "help"]
        }
        
        scores = {}
        for topic, kws in TOPIC_KEYWORDS.items():
            score = sum(1 for kw in kws if kw in text_lower)
            scores[topic] = score
            
        best_topic = max(scores, key=scores.get)
        max_score = scores[best_topic]
        
        if max_score > 0:
            theme = match_closest_category(best_topic, categories)
            if best_topic == "Pricing & Refund Issues":
                root_cause = "User dissatisfied with prices, fees, or refund handling"
            elif best_topic == "Product Quality & Freshness":
                root_cause = "User complaining about damaged, expired, or low quality fresh items"
            elif best_topic == "Delivery Speed & Delay":
                root_cause = "User reporting slow delivery times or delay in order fulfillment"
            elif best_topic == "App Navigation & Clutter":
                root_cause = "User reporting UI clutter or issues exploring categories"
            elif best_topic == "Customer Support Issues":
                root_cause = "User dissatisfied with support agent response or complaint serialness"
        else:
            # Check if there is an "Other" or "General" category in the list
            for cat in categories:
                if any(g in cat.lower() for g in ["other", "general", "uncategorized", "feedback"]):
                    theme = cat
                    break
            if not theme:
                theme = categories[0] if categories else "Fresh Produce Out-Of-Stock"
                
    # 3. Sentiment Overrides
    if any(w in text_lower for w in ["love", "great", "excellent", "fast", "convenient", "amazing"]):
        sentiment = "Positive"
    elif any(w in text_lower for w in ["worst", "hate", "terrible", "useless", "uninstall", "fraud", "out of stock", "empty"]):
        sentiment = "Highly Frustrated"
        
    # 4. Cohort Overrides
    if any(w in text_lower for w in ["weekly", "every day", "daily", "always"]):
        user_cohort = "Power User"
    elif any(w in text_lower for w in ["first time", "tried", "new"]):
        user_cohort = "New Shopper"

    return {
        "theme": theme,
        "sentiment": sentiment,
        "user_type": user_cohort,
        "root_cause": root_cause[:150],
        "confidence_score": 4 if theme else 3
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
    Uses Groq JSON mode to classify a raw review text against the active taxonomy.
    """
    if not GROQ_API_KEY:
        return rule_based_fallback(text, categories)
        
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
        client = Groq(api_key=GROQ_API_KEY, timeout=6.0)
        response_text = create_groq_completion(
            client=client,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=200
        )
        result = clean_llm_json(response_text)
        
        if result:
            # Validate output fields and fallbacks
            theme = result.get("pain_point_category")
            result["pain_point_category"] = match_closest_category(theme, categories)
                
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
        print(f"[Classifier] Groq API call failed: {e}.")
        if raise_on_error:
            raise e
        print("Falling back to rules.")
        
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
        
    client = Groq(api_key=GROQ_API_KEY, timeout=6.0)
    
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
                    "user_type": "Casual Shopper",
                    "root_cause": f"AI Failure: {str(e_single)[:100]}",
                    "confidence_score": 1,
                    "spot_checked": True,
                    "spot_check_valid": None
                })
        return results
