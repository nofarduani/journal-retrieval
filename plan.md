# Weekly Research Digest Agent — Implementation Plan
 
## Context
 
A marketing researcher studying consumer behavior and technology needs to stay current with a fast-moving field. This agent automates weekly discovery across two sources — 26 top academic journals (via OpenAlex) and Bluesky social network (1st + 2nd degree connections) — using Claude Opus to filter for relevance, then delivers a formatted email digest every Friday morning.
 
---
 
## Project Structure
 
```
journal-retrieval/
├── main.py                    # Entry point — orchestrates the full pipeline
├── config.py                  # Constants: journal ISSNs, defaults, settings
├── openalex_client.py         # Fetch papers from OpenAlex API
├── bluesky_client.py          # Fetch posts from Bluesky via atproto SDK
├── social_graph.py            # Build/cache/refresh the Bluesky social graph
├── relevance_filter.py        # Claude Opus API calls to filter & score items
├── email_sender.py            # Format HTML email & send via Gmail SMTP
├── memory.py                  # Load/save/check the seen-items JSON file
├── requirements.txt           # Python dependencies
├── .env.example               # Template for credentials
├── .gitignore                 # Ignore .env, __pycache__, etc.
├── data/
│   ├── memory.json            # Seen items (DOIs, post URIs) — committed to repo
│   └── social_graph.json      # Cached Bluesky social graph — committed to repo
└── .github/
    └── workflows/
        └── weekly_digest.yml  # GitHub Actions cron workflow
```
 
---
 
## Module Details
 
### 1. `config.py` — Constants & Settings
 
- **JOURNALS dict**: Maps journal name -> ISSN(s) for all 26 journals. These will be used to query OpenAlex via `primary_location.source.issn:<ISSN>` filter.
- **LOOKBACK_DAYS**: 7 (how far back to search)
- **SECOND_DEGREE_CAP**: 1000
- **GRAPH_REFRESH_DAYS**: 30
- **BATCH_SIZE**: Number of items per Claude API call for filtering (e.g., 10 papers or 20 posts per batch)
- Loads env vars: `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`, `ANTHROPIC_API_KEY`, `OPENALEX_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `RECIPIENT_EMAIL`
 
### 2. `openalex_client.py` — Academic Paper Fetching
 
**`fetch_recent_papers(journals: dict, days: int) -> list[dict]`**
 
For each journal ISSN:
- Call `GET https://api.openalex.org/works?filter=primary_location.source.issn:{issn},from_created_date:{7_days_ago}&per_page=50&select=id,doi,title,authorships,primary_location,abstract_inverted_index,publication_date`
- Handle pagination via `cursor` parameter if > 50 results
- Include `api_key` query param if available (for higher rate limits)
- Rate limit: add small delay between requests (~0.1s)
 
**`reconstruct_abstract(inverted_index: dict) -> str`**
 
- Convert OpenAlex inverted abstract index to plaintext
- Algorithm: create array of (word, position) from the dict, sort by position, join with spaces
 
**Output format per paper:**
```python
{
    "id": "W1234567890",
    "doi": "https://doi.org/10.1234/...",
    "title": "...",
    "authors": ["Author One", "Author Two"],
    "journal": "Journal of Marketing Research",
    "abstract": "Full reconstructed abstract text...",
    "publication_date": "2026-04-05",
    "url": "https://doi.org/10.1234/..."
}
```
 
### 3. `bluesky_client.py` — Post Fetching
 
**`fetch_posts_from_accounts(accounts: list[str], days: int) -> list[dict]`**
 
- Authenticate using `atproto.Client` with handle + app password
- For each account DID, call `client.app.bsky.feed.get_author_feed(actor=did, limit=50)`
- Filter posts to only those within the last `days` days (compare `created_at`)
- Skip reposts (only original posts)
- Paginate if needed via cursor
 
**Output format per post:**
```python
{
    "uri": "at://did:plc:.../app.bsky.feed.post/...",
    "author_handle": "researcher.bsky.social",
    "author_name": "Dr. Jane Smith",
    "text": "Post content...",
    "created_at": "2026-04-05T10:30:00Z",
    "url": "https://bsky.app/profile/researcher.bsky.social/post/..."
}
```
 
### 4. `social_graph.py` — Social Graph Management
 
**`build_or_refresh_graph(handle: str, force: bool = False) -> dict`**
 
1. Check `data/social_graph.json` for `last_refreshed` timestamp
2. If < 30 days old and not `force`, load from cache
3. Otherwise, rebuild:
   - Get 1st degree: `client.app.bsky.graph.get_follows(actor=handle)` + `get_followers(actor=handle)` (paginate both)
   - Deduplicate into a set of 1st degree DIDs
   - For each 1st degree DID, get THEIR follows + followers (paginate). This is the expensive part — rate-limit with ~0.2s delays
   - Collect all 2nd degree accounts, count how many times each appears (popularity in user's network)
   - Remove 1st degree accounts from 2nd degree set
   - Sort 2nd degree by occurrence count (descending), cap at 1000
   - Save to `data/social_graph.json`
 
**Graph cache schema (`data/social_graph.json`):**
```json
{
    "last_refreshed": "2026-04-01T08:00:00Z",
    "handle": "user.bsky.social",
    "first_degree": [
        {"did": "did:plc:abc...", "handle": "friend.bsky.social", "display_name": "Friend"}
    ],
    "second_degree": [
        {"did": "did:plc:xyz...", "handle": "popular.bsky.social", "display_name": "Popular Researcher", "network_score": 15}
    ]
}
```
 
### 5. `relevance_filter.py` — AI Filtering via Claude Opus
 
**`filter_papers(papers: list[dict]) -> list[dict]`**
**`filter_posts(posts: list[dict]) -> list[dict]`**
 
- Uses `anthropic.Anthropic()` client with `ANTHROPIC_API_KEY`
- Model: `claude-opus-4-6`
- Batches items (10 papers per call, 20 posts per call) to reduce API calls
- Each call sends a system prompt (placeholder for user to customize) + the batch as structured data
- Claude returns JSON: for each item, `{"relevant": true/false, "note": "1-2 sentence explanation"}`
- Only items marked `relevant: true` are kept, with the `note` attached
 
**Placeholder prompt structure (user will customize):**
```
PAPER_FILTER_PROMPT = """You are a research relevance filter for a marketing 
researcher. [PLACEHOLDER: User will customize this prompt with specific 
research interests and filtering criteria.]
 
Given the following batch of academic papers, determine which are relevant.
Return a JSON array..."""
 
POST_FILTER_PROMPT = """You are a social media relevance filter for a marketing 
researcher. [PLACEHOLDER: User will customize this prompt with specific 
research interests and filtering criteria.]
 
Given the following batch of Bluesky posts, determine which are relevant.
Return a JSON array..."""
```
 
### 6. `memory.py` — Deduplication State
 
**`load_memory() -> dict`**  
**`save_memory(memory: dict)`**  
**`is_seen(memory: dict, item_id: str) -> bool`**  
**`mark_seen(memory: dict, item_id: str)`**
 
**Memory schema (`data/memory.json`):**
```json
{
    "seen_paper_dois": ["https://doi.org/10.1234/...", "..."],
    "seen_post_uris": ["at://did:plc:.../app.bsky.feed.post/...", "..."],
    "last_run": "2026-04-04T15:00:00Z"
}
```
 
- Memory is checked BEFORE AI filtering (no point filtering duplicates)
- Memory is updated AFTER successful email send
- Prune entries older than 90 days to prevent unbounded growth
 
### 7. `email_sender.py` — HTML Email via Gmail SMTP
 
**`send_digest(papers: list[dict], posts: list[dict])`**
 
- Uses `smtplib` + `email.mime` (stdlib — no external dependency)
- SMTP server: `smtp.gmail.com:587` with STARTTLS
- Auth with `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD`
- Sends to `RECIPIENT_EMAIL`
- Subject: `"Research Digest — Week of {date}"`
 
**HTML email structure:**
```
Subject: Research Digest — Week of April 4, 2026
 
## Relevant Academic Papers (X found)
For each paper:
  - Title (linked to DOI)
  - Authors | Journal | Date
  - Abstract (collapsible or truncated)
  - WHY IT'S RELEVANT: [AI note]
 
## Relevant Bluesky Posts (X found)  
For each post:
  - Poster Name (@handle) — linked to profile
  - Post text
  - WHY IT'S RELEVANT: [AI note]
 
---
Footer: Generated by journal-retrieval agent. Run at {timestamp}.
```
 
### 8. `main.py` — Orchestrator
 
```python
def main():
    1. Load memory from data/memory.json
    2. Fetch papers from OpenAlex (all 26 journals, last 7 days)
    3. Remove already-seen papers (check DOIs against memory)
    4. Build/refresh Bluesky social graph if stale (>30 days)
    5. Fetch posts from all 1st + 2nd degree accounts (last 7 days)
    6. Remove already-seen posts (check URIs against memory)
    7. Run AI filter on new papers -> relevant papers with notes
    8. Run AI filter on new posts -> relevant posts with notes
    9. If any relevant items found, send email digest
    10. Update memory with all fetched item IDs (not just relevant ones)
    11. Save memory to data/memory.json
    12. Log summary: X papers fetched, Y relevant, Z posts fetched, W relevant
```
 
---
 
## GitHub Actions Workflow (`.github/workflows/weekly_digest.yml`)
 
```yaml
name: Weekly Research Digest
on:
  schedule:
    - cron: '0 15 * * 5'   # Every Friday at 15:00 UTC = 8:00 AM PT
  workflow_dispatch:         # Allow manual trigger
 
jobs:
  digest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: python main.py
        env:
          BLUESKY_HANDLE: ${{ secrets.BLUESKY_HANDLE }}
          BLUESKY_APP_PASSWORD: ${{ secrets.BLUESKY_APP_PASSWORD }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENALEX_API_KEY: ${{ secrets.OPENALEX_API_KEY }}
          GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          RECIPIENT_EMAIL: ${{ secrets.RECIPIENT_EMAIL }}
      - name: Commit updated memory and social graph
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/memory.json data/social_graph.json
          git diff --cached --quiet || git commit -m "Update memory and social graph after digest run"
          git push
```
 
---
 
## `.env.example`
 
```
BLUESKY_HANDLE=yourhandle.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
ANTHROPIC_API_KEY=sk-ant-...
OPENALEX_API_KEY=your_openalex_key
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
RECIPIENT_EMAIL=you@gmail.com
```
 
---
 
## Dependencies (`requirements.txt`)
 
```
atproto>=0.0.55
anthropic>=0.40.0
httpx>=0.27.0
python-dotenv>=1.0.0
```
 
---
 
## Error Handling & Resilience
 
- **OpenAlex**: Retry on 429 (rate limit) with exponential backoff (3 retries). Skip individual journals that fail after retries; log warning.
- **Bluesky**: Retry on network errors (3 retries). Skip individual accounts that fail. If auth fails, abort with clear error message.
- **Claude API**: Retry on 429/500 (3 retries). If a batch fails, skip it and log. Parse JSON response with fallback for malformed output.
- **Email**: Retry send 3 times. If email fails, still save memory (don't lose dedup state).
- **Social graph build**: If graph build fails partway, save what we have. Next run will detect stale graph and retry.
- **All errors**: Log to stdout (captured by GH Actions). Never crash silently.
 
---
 
## Cost Estimation (per weekly run)
 
- **Papers**: ~26 journal queries to OpenAlex (free). Expect 50-200 new papers/week across all journals.
- **Bluesky**: ~1000-1100 feed fetches (1st + 2nd degree accounts). Graph refresh ~monthly adds ~200-500 additional calls.
- **Claude Opus filtering**: 
  - Papers: ~200 papers / 10 per batch = ~20 API calls
  - Posts: Highly variable. If 5000 posts from network / 20 per batch = ~250 API calls
  - Opus pricing: ~$15/1M input, ~$75/1M output tokens
  - Estimated cost per run: **$2-10** depending on post volume (mostly input tokens for abstracts and post text)
 
---
 
## Implementation Order
 
1. `config.py` — journal ISSNs, env var loading, constants
2. `memory.py` — simple JSON read/write/check
3. `openalex_client.py` — paper fetching + abstract reconstruction
4. `social_graph.py` — graph building and caching
5. `bluesky_client.py` — post fetching from account lists
6. `relevance_filter.py` — Claude API filtering with placeholder prompts
7. `email_sender.py` — HTML formatting and SMTP sending
8. `main.py` — wire everything together
9. `.github/workflows/weekly_digest.yml` — CI workflow
10. `.env.example`, `.gitignore`, `requirements.txt` — project scaffolding
11. Initialize `data/memory.json` and `data/social_graph.json` with empty defaults
 
---
 
## Verification
 
1. **Unit test locally**: Set up `.env` with real credentials, run `python main.py`, verify email arrives with correct formatting
2. **Test individual modules**: Each module can be tested independently (e.g., `python -c "from openalex_client import fetch_recent_papers; ..."`)
3. **Test GitHub Actions**: Push to branch, manually trigger workflow via `workflow_dispatch`, check Actions logs and verify email
4. **Edge cases to verify**: 
   - No new papers found (email should still send with "No new papers this week")
   - No relevant items after filtering (send a brief "nothing new" email)
   - Empty social graph (first run before graph is built)
   - Memory file doesn't exist yet (first run — create it)