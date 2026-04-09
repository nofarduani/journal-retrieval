"""Phase 1: Fetch papers and posts, deduplicate, write pre-batched candidates."""

import json
import logging
import math
import os
import sys

import config
from memory import load_memory, is_seen
from openalex_client import fetch_recent_papers
from bluesky_client import create_client, fetch_posts_from_accounts
from social_graph import build_or_refresh_graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PAPER_BATCH_SIZE = 20
POST_BATCH_SIZE = 25


def _write_batches(items, item_type, batch_size, batches_dir):
    """Split items into batch files and write to batches_dir.

    Returns the number of batches written.
    """
    if not items:
        return 0

    num_batches = math.ceil(len(items) / batch_size)
    for i in range(num_batches):
        batch = items[i * batch_size : (i + 1) * batch_size]
        batch_id = f"{item_type}_{i + 1:03d}"
        filepath = os.path.join(batches_dir, f"{batch_id}.json")
        with open(filepath, "w") as f:
            json.dump({"batch_id": batch_id, "type": item_type, "items": batch}, f, indent=2)

    return num_batches


def main():
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/results", exist_ok=True)
    os.makedirs("reports", exist_ok=True)

    # Set up batches directory (clean any leftovers)
    batches_dir = "data/batches"
    os.makedirs(batches_dir, exist_ok=True)
    for f in os.listdir(batches_dir):
        if f.endswith(".json"):
            os.remove(os.path.join(batches_dir, f))

    # Clean up leftover result files
    results_dir = "data/results"
    for f in os.listdir(results_dir):
        if f.endswith(".json"):
            os.remove(os.path.join(results_dir, f))

    memory = load_memory()
    logger.info(
        "Loaded memory — %d seen papers, %d seen posts",
        len(memory["seen_paper_dois"]),
        len(memory["seen_post_uris"]),
    )

    # Fetch papers
    logger.info(
        "Fetching papers from %d journals (last %d days)...",
        len(config.JOURNALS),
        config.LOOKBACK_DAYS,
    )
    all_papers = fetch_recent_papers(config.JOURNALS, config.LOOKBACK_DAYS)
    new_papers = [
        p for p in all_papers if not is_seen(memory, p["doi"] or p["id"], "paper")
    ]
    logger.info("Papers: %d fetched, %d new", len(all_papers), len(new_papers))

    # Fetch posts
    bsky_client = create_client()
    graph = build_or_refresh_graph(bsky_client, config.BLUESKY_HANDLE)
    all_accounts = graph["first_degree"] + graph["second_degree"]
    logger.info(
        "Social graph: %d 1st degree, %d 2nd degree",
        len(graph["first_degree"]),
        len(graph["second_degree"]),
    )

    all_posts = fetch_posts_from_accounts(
        bsky_client, all_accounts, config.LOOKBACK_DAYS
    )
    new_posts = [p for p in all_posts if not is_seen(memory, p["uri"], "post")]
    logger.info("Posts: %d fetched, %d new", len(all_posts), len(new_posts))

    # Write pre-batched candidate files
    paper_batches = _write_batches(new_papers, "papers", PAPER_BATCH_SIZE, batches_dir)
    post_batches = _write_batches(new_posts, "posts", POST_BATCH_SIZE, batches_dir)
    logger.info(
        "Wrote %d paper batches + %d post batches to data/batches/",
        paper_batches,
        post_batches,
    )

    # Write metadata for the scheduled task to read (small file)
    meta = {
        "total_papers_fetched": len(all_papers),
        "total_posts_fetched": len(all_posts),
        "new_papers": len(new_papers),
        "new_posts": len(new_posts),
        "paper_batches": paper_batches,
        "post_batches": post_batches,
    }
    with open("data/candidates_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    # Write all fetched items (for marking as seen in Phase 3)
    all_fetched = {
        "papers": [{"doi": p["doi"], "id": p["id"]} for p in all_papers],
        "posts": [{"uri": p["uri"]} for p in all_posts],
    }
    with open("data/all_fetched.json", "w") as f:
        json.dump(all_fetched, f, indent=2)

    logger.info(
        "Phase 1 complete. %d candidate papers (%d batches), %d candidate posts (%d batches)",
        len(new_papers),
        paper_batches,
        len(new_posts),
        post_batches,
    )

    # Exit with code 2 if zero candidates (signal to skip Phase 2)
    if not new_papers and not new_posts:
        logger.info("No new candidates to filter. Exiting with code 2.")
        sys.exit(2)


if __name__ == "__main__":
    main()
