"""
Unit Tests for AI-Native Review Discovery Engine
Validates text cleaning, MD5 hashing, JSON extraction, and classification fallbacks.
"""

import pytest
import json
from pipeline import clean_text, compute_md5, clean_llm_json, rule_based_fallback, analyze_review_with_groq

def test_compute_md5():
    """Verify MD5 generation is deterministic and consistent."""
    hash1 = compute_md5("App Store", "12345")
    hash2 = compute_md5("App Store", "12345")
    hash3 = compute_md5("Reddit", "12345")
    
    assert hash1 == hash2
    assert hash1 != hash3
    assert len(hash1) == 32

def test_clean_text_normal():
    """Verify that clean_text removes extra spacing and HTML tags."""
    raw = "  Hello   World! <br> This is <b>bold</b> text.  "
    expected = "Hello World! This is bold text."
    assert clean_text(raw) == expected

def test_clean_text_truncation():
    """Verify that clean_text truncates to exactly 800 characters."""
    long_text = "a" * 1000
    cleaned = clean_text(long_text)
    assert len(cleaned) == 800
    assert cleaned == "a" * 800

def test_clean_llm_json_clean():
    """Verify clean_llm_json parses neat JSON."""
    raw = '{"theme": "Echo Chamber", "sentiment": "Negative", "user_type": "Power User", "root_cause": "Trapped in loops"}'
    parsed = clean_llm_json(raw)
    assert parsed is not None
    assert parsed["theme"] == "Echo Chamber"
    assert parsed["root_cause"] == "Trapped in loops"

def test_clean_llm_json_markdown():
    """Verify clean_llm_json handles markdown wrappers and conversational text."""
    raw = 'Sure! Here is the JSON:\n```json\n{"theme": "Smart Shuffle Failure", "sentiment": "Highly Frustrated", "user_type": "Playlist Curator", "root_cause": "Smart shuffle repeats tracks"}\n```\nHope this helps!'
    parsed = clean_llm_json(raw)
    assert parsed is not None
    assert parsed["theme"] == "Smart Shuffle Failure"
    assert parsed["user_type"] == "Playlist Curator"

def test_clean_llm_json_invalid():
    """Verify clean_llm_json returns None for invalid or missing braces."""
    raw = "This is not json at all."
    assert clean_llm_json(raw) is None

def test_rule_based_fallback():
    """Verify rule-based local classifier categorizes text properly based on keywords."""
    res_shuffle = rule_based_fallback("Spotify's smart shuffle feature is terrible, same songs keep playing.")
    assert res_shuffle["theme"] == "Smart Shuffle Failure"
    assert res_shuffle["user_type"] == "Playlist Curator"
    
    res_echo = rule_based_fallback("I am stuck in an echo chamber of the same songs on loop.")
    assert res_echo["theme"] == "Echo Chamber"
    assert res_echo["sentiment"] == "Highly Frustrated"
    
    res_clutter = rule_based_fallback("The user interface has too much clutter and bad UI design.")
    assert res_clutter["theme"] == "UI/UX Clutter"
    assert res_clutter["user_type"] == "Casual Listener"

    # Mixed-sentiment case (should be classified as Negative since it contains complaints/criticisms)
    mixed_text = (
        "Update: below criticism still holds if true. I've taken family premium and that's much more affordable. "
        "other than that, a great music app with amazing recommendations. 2 stars just because they made shuffling "
        "and changing the songs premium features. The initial criticism: Ads are not enough? Too much corporat-ism! "
        "Besides that, with premium, it's a great music app with amazing recommendations algorithm and good UI and features."
    )
    res_mixed = rule_based_fallback(mixed_text)
    assert res_mixed["theme"] == "Ad & Subscription Barriers"
    assert res_mixed["sentiment"] == "Negative"

    # Forced shuffle reviews (should be classified as Ad & Subscription Barriers)
    f_shuffle_1 = "I hope that they can remove the optional cues to normal, because right now they're premium and it's kind of annoying, because I don't like my playlist in shuffle I want them an order. So I hope they can change it. but the app is nice"
    f_shuffle_2 = "Not enough control You literally have no choice in what you listen too unless you pay, it forces your list too shuffle with random songs and you can’t loop it. This app just wants money."
    f_shuffle_3 = "Is it because of the new update that I can no longer switch it off shuffle mode or skip songs? If so, I have to say it's ridiculous. Why do you have to limit the free account so much?"
    
    assert rule_based_fallback(f_shuffle_1)["theme"] == "Ad & Subscription Barriers"
    assert rule_based_fallback(f_shuffle_2)["theme"] == "Ad & Subscription Barriers"
    assert rule_based_fallback(f_shuffle_3)["theme"] == "Ad & Subscription Barriers"

def test_analyze_review_with_groq_fallback_when_no_key(monkeypatch):
    """Verify analyze_review_with_groq falls back to rule-based classification if no API key exists."""
    # Temporarily remove GROQ_API_KEY from environment
    monkeypatch.setenv("GROQ_API_KEY", "")
    
    text = "The smart shuffle is looping tracks."
    result = analyze_review_with_groq(text)
    
    # Should execute local fallback
    assert result["theme"] == "Smart Shuffle Failure"
    assert result["user_type"] == "Playlist Curator"
