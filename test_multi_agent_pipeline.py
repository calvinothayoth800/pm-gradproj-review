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
    categories = ["Fresh Produce Out-Of-Stock", "Category Browse Clutter", "Reorder Widget Convenience"]
    
    valid_batch = [
        {"review_id": "id_1", "theme": "Fresh Produce Out-Of-Stock", "sentiment": "Negative", "user_type": "Casual Shopper", "root_cause": "Veggies out of stock"},
        {"review_id": "id_2", "theme": "CategoryBrowseClutter", "sentiment": "Negative", "user_type": "Power User", "root_cause": "Cluttered menu"} # Theme not in categories, counts as invalid
    ]
    
    # 1 out of 2 are valid => 50% pass rate. Should fail 95% gate
    is_valid, msg = orchestrator.validate_classification(valid_batch, categories)
    assert is_valid == False
    
    perfect_batch = [
        {"review_id": "id_1", "theme": "Fresh Produce Out-Of-Stock", "sentiment": "Negative", "user_type": "Casual Shopper", "root_cause": "Veggies out of stock"},
        {"review_id": "id_2", "theme": "Reorder Widget Convenience", "sentiment": "Positive", "user_type": "Power User", "root_cause": "Smooth reorder widget"}
    ]
    # 100% pass rate. Should pass 95% gate
    is_valid, msg = orchestrator.validate_classification(perfect_batch, categories)
    assert is_valid == True

def test_rule_based_fallback():
    """Verify local classification rules function when API is offline."""
    categories = ["Fresh Produce Out-Of-Stock", "Category Browse Clutter", "Reorder Widget Convenience"]
    
    res_stock = classifier.rule_based_fallback("Veggies are always out of stock, empty lists.", categories)
    assert "Stock" in res_stock["theme"] or "stock" in res_stock["theme"].lower()
    assert res_stock["sentiment"] == "Highly Frustrated"
    
    res_reorder = classifier.rule_based_fallback("Love the new 1-click reorder widget!", categories)
    assert "Reorder" in res_reorder["theme"] or "reorder" in res_reorder["theme"].lower()
    assert res_reorder["sentiment"] == "Positive"
