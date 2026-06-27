# Edge Cases & Architectural Mitigations

This document outlines the identified failure modes for the AI-Native Review Discovery Engine and how the codebase addresses them to protect our free-tier resources and maintain database integrity.

## 1. Third-Party Scraper Exceptions
- **Risk**: Changes to Apple App Store JSON formats or Reddit API structures will cause standard ingestion loops to crash.
- **Mitigation**:
  - `scrape_app_store()` and `scrape_reddit()` functions are wrapped in isolated `try-except` blocks.
  - If a network error, HTTP 403/429 status code, or structural parsing error is encountered, the script logs the warning and continues.
  - The pipeline does not halt; other sources (including the Google Play ingestion simulator) are still processed normally.

## 2. Reddit API 429 (Too Many Requests)
- **Risk**: Reddit blocks requests that use a generic Python user-agent, returning `429 Too Many Requests`.
- **Mitigation**:
  - We explicitly set a unique user-agent header: `User-Agent: AntigravityReviewDiscoveryEngine/1.0 (Growth PM Project)`.
  - This informs Reddit of our application and reduces the likelihood of automated bot bans.

## 3. Groq API Daily Volume Depletion (Rate Limits)
- **Risk**: Groq free-tier has low Daily Request limits (RPD) and Token ceilings (TPM). An influx of 5,000 unprocessed records would instantly exhaust our quota.
- **Mitigation**:
  - **Batch Ceiling**: Inside `pipeline.py`, the processing loop is capped at `MAX_BATCH_SIZE = 900` records per run. If the delta queue is larger, the script stops after 900 records, saves its progress, and terminates safely.
  - **Sequential Delay**: A strict `3.0s` sleep interval (`time.sleep(3.0)`) is enforced between sequential LLM calls to stay comfortably below the `30 RPM` rate limit.

## 4. Malformed or Conversational LLM JSON Outputs
- **Risk**: Even with temperature=0.1, the LLM may output markdown wrappers (e.g. ` ```json `) or leading conversational phrases ("Here is the classification..."), causing `json.loads` to throw an error.
- **Mitigation**:
  - **Brace Extraction**: `clean_llm_json()` uses text slicing to isolate the substring between the first `{` and last `}` characters. This removes any conversational fluff or backticks before parsing.
  - **Validation & Fallback**: After JSON parsing, the script validates that the returned fields exist and are members of the allowed database constraints (`THEME_ENUM`, `SENTIMENT_ENUM`, `USER_TYPE_ENUM`).
  - **Graceful Fallback**: If LLM parsing still fails, or the network times out, `pipeline.py` executes a local keyword-based rule classifier (`rule_based_fallback()`) as a safety net, avoiding database constraints errors.

## 5. Duplicate Data Ingestion
- **Risk**: Daily scraper sweeps will pull overlapping reviews, leading to duplicate database records.
- **Mitigation**:
  - We compute a deterministic primary key `review_id` as the MD5 hash of the source prefix and the native review ID (`source + ":" + platform_id`).
  - We use PostgREST upsert headers `Prefer: resolution=merge-duplicates` in `pipeline.py` and `seed_data.py`. This overwrites/ignores duplicates instead of failing.
