import os
import pytest
import scrapers
import orchestrator
import classifier
import auditor

def test_clean_text():
    """Verify that clean_text removes extra spacing and HTML tags."""
    raw = "  Hello   Blinkit! <br> Browse <b>organic veggies</b> now.  "
    expected = "Hello Blinkit! Browse organic veggies now."
    assert scrapers.clean_text(raw) == expected

def test_compute_md5():
    """Verify MD5 generation is deterministic and unique."""
    h1 = scrapers.compute_md5("App Store", "review_123")
    h2 = scrapers.compute_md5("App Store", "review_123")
    h3 = scrapers.compute_md5("Google Play", "review_123")
    
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 32

def test_validate_ingestion():
    """Verify ingestion validation catches malformed or empty batches."""
    valid_batch = [
        {"review_id": "id_1", "source": "App Store", "text": "Very clean categories.", "timestamp": "2026-07-20T12:00:00Z"},
        {"review_id": "id_2", "source": "Google Play", "text": "Reorder works fine.", "timestamp": "2026-07-20T12:05:00Z"}
    ]
    is_valid, msg = orchestrator.validate_ingestion(valid_batch)
    assert is_valid == True
    
    empty_batch = []
    is_valid, msg = orchestrator.validate_ingestion(empty_batch)
    assert is_valid == False
    
    malformed_batch = [
        {"review_id": "id_1", "source": "App Store", "timestamp": "2026-07-20T12:00:00Z"}  # Missing text
    ]
    is_valid, msg = orchestrator.validate_ingestion(malformed_batch)
    assert is_valid == False

def test_validate_classification():
    """Verify classification validation calculates rates correctly."""
    categories = ["Habit_Loop_Repetitive_Buying", "UI_Category_Visibility_Clutter", "Price_Value_Trial_Hesitation"]
    
    valid_batch = [
        {"review_id": "id_1", "theme": "Habit_Loop_Repetitive_Buying", "sentiment": "Negative", "user_type": "Power_Grocery_Shopper", "root_cause": "Routine milk orders"},
        {"review_id": "id_2", "theme": "InvalidThemeName", "sentiment": "Negative", "user_type": "Unspecified_Insufficient_Context", "root_cause": "Cluttered menu"} # Theme not in categories, counts as invalid
    ]
    
    # 1 out of 2 are valid => 50% pass rate. Should fail 95% gate
    is_valid, msg = orchestrator.validate_classification(valid_batch, categories)
    assert is_valid == False
    
    perfect_batch = [
        {"review_id": "id_1", "theme": "Habit_Loop_Repetitive_Buying", "sentiment": "Negative", "user_type": "Power_Grocery_Shopper", "root_cause": "Routine milk orders"},
        {"review_id": "id_2", "theme": "Price_Value_Trial_Hesitation", "sentiment": "Positive", "user_type": "Category_Explorer", "root_cause": "Overpriced non-grocery"}
    ]
    # 100% pass rate. Should pass 95% gate
    is_valid, msg = orchestrator.validate_classification(perfect_batch, categories)
    assert is_valid == True

def test_rule_based_fallback():
    """Verify local classification rules function when API is offline."""
    categories = ["Habit_Loop_Repetitive_Buying", "UI_Category_Visibility_Clutter", "Search_Only_Bypass", "Out_Of_Scope_Operations"]
    
    res_stock = classifier.rule_based_fallback("Rider was late by 30 mins, refund not processed.", categories)
    assert "Out_Of_Scope" in res_stock["theme"] or "Operations" in res_stock["theme"] or res_stock["is_discovery_relevant"] == False
    assert res_stock["sentiment"] == "Highly Frustrated"
    
    res_reorder = classifier.rule_based_fallback("Love the 1-click reorder widget for my daily milk!", categories)
    assert "Habit" in res_reorder["theme"] or "Reorder" in res_reorder["theme"]
    assert res_reorder["sentiment"] == "Positive"
