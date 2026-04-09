# journal-retrieval

Weekly Research Digest Agent — fetches academic papers from OpenAlex and Bluesky posts, filters for relevance using Claude Code subagents, and sends an email digest.

## Architecture

The pipeline runs in three phases:

1. **Phase 1** (`fetch_and_prepare.py`): Fetches papers + posts, deduplicates, writes pre-batched files to `data/batches/` and metadata to `data/candidates_meta.json`
2. **Phase 2** (Claude subagents): Reads `data/candidates_meta.json` to know batch count, spawns subagents that each read one file from `data/batches/` and write results to `data/results/`
3. **Phase 3** (`send_and_finalize.py`): Reads `data/results/`, verifies Phase 2 ran, sends email digest, saves report, updates memory

## How to run locally

```bash
pip install -r requirements.txt
python main.py
```

Note: Local runs skip Phase 2 (AI filtering). For full runs with filtering, use the Claude Code scheduled task.

## Environment variables

Set in `.env` (local) or in the Claude Code cloud environment (scheduled runs):

- `BLUESKY_HANDLE` / `BLUESKY_APP_PASSWORD` — Bluesky auth
- `OPENALEX_API_KEY` — OpenAlex (optional, for higher rate limits)
- `BREVO_API_KEY` — Brevo API key for sending email
- `SENDER_EMAIL` — verified sender address (e.g. your Gmail)
- `RECIPIENT_EMAIL` — digest recipient

## Filter criteria

Edit `filter_criteria.md` to customize what counts as "relevant" for papers and posts.

## Automated runs

This project runs weekly via a Claude Code scheduled task. The task:
1. Runs `python fetch_and_prepare.py` (Phase 1)
2. Reads `data/candidates_meta.json` for batch counts
3. Spawns subagents that each read one file from `data/batches/` and write filtered results to `data/results/` (Phase 2)
4. Runs `python send_and_finalize.py` (Phase 3)
5. Commits updated `data/memory.json`, `data/social_graph.json`, and `reports/` files and pushes to `main`

**Do not modify Python source files during automated runs.**
