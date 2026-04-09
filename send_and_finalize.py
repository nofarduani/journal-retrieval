"""Phase 3: Collect filtered results, send digest, update memory.

Safety: refuses to update memory if Phase 2 didn't produce results
when batches were expected. This prevents unfiltered items from being
permanently marked as seen.
"""

import json
import logging
import os
import sys

from memory import load_memory, mark_seen, prune_memory, save_memory
from email_sender import send_digest, save_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _load_meta():
    """Load candidates metadata to know what Phase 2 should have processed."""
    try:
        with open("data/candidates_meta.json") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _count_result_files():
    """Count how many batch result files Phase 2 produced."""
    results_dir = "data/results"
    if not os.path.exists(results_dir):
        return 0
    return sum(1 for f in os.listdir(results_dir) if f.endswith(".json"))


def _load_results():
    """Load and merge all batch result files from data/results/."""
    results_dir = "data/results"
    relevant_papers = []
    relevant_posts = []

    if not os.path.exists(results_dir):
        return relevant_papers, relevant_posts

    for filename in sorted(os.listdir(results_dir)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(results_dir, filename)
        try:
            with open(filepath) as f:
                batch_result = json.load(f)
            relevant_papers.extend(batch_result.get("papers", []))
            relevant_posts.extend(batch_result.get("posts", []))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read result file %s: %s", filepath, exc)

    return relevant_papers, relevant_posts


def main():
    meta = _load_meta()
    expected_batches = 0
    if meta:
        expected_batches = meta.get("paper_batches", 0) + meta.get("post_batches", 0)

    result_count = _count_result_files()

    # Guard: if batches were expected but zero results exist, Phase 2 didn't run.
    # Do NOT update memory — those items need to be filtered on the next run.
    if expected_batches > 0 and result_count == 0:
        logger.error(
            "Phase 2 produced 0 result files but %d batches were expected. "
            "Memory will NOT be updated so items can be retried next run. "
            "Saving an empty report for the record.",
            expected_batches,
        )
        save_report([], [])
        sys.exit(1)

    if expected_batches > 0 and result_count < expected_batches:
        logger.warning(
            "Phase 2 produced %d of %d expected result files. "
            "Proceeding with partial results.",
            result_count, expected_batches,
        )

    relevant_papers, relevant_posts = _load_results()
    logger.info(
        "Collected results: %d relevant papers, %d relevant posts",
        len(relevant_papers), len(relevant_posts),
    )

    # Send email
    if relevant_papers or relevant_posts:
        email_sent = send_digest(relevant_papers, relevant_posts)
    else:
        logger.info("No relevant items found — skipping email")
        email_sent = True

    # Save report
    report_path = save_report(relevant_papers, relevant_posts)
    logger.info("Report saved to %s", report_path)

    # Update memory: mark ALL fetched items as seen
    memory = load_memory()
    try:
        with open("data/all_fetched.json") as f:
            all_fetched = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("Could not load all_fetched.json — memory update may be incomplete")
        all_fetched = {"papers": [], "posts": []}

    for p in all_fetched["papers"]:
        mark_seen(memory, p["doi"] or p["id"], "paper")
    for p in all_fetched["posts"]:
        mark_seen(memory, p["uri"], "post")

    prune_memory(memory)
    save_memory(memory)
    logger.info(
        "Memory saved — now tracking %d papers, %d posts",
        len(memory["seen_paper_dois"]), len(memory["seen_post_uris"]),
    )

    logger.info(
        "=== DIGEST COMPLETE === Papers: %d relevant | Posts: %d relevant | Email: %s",
        len(relevant_papers), len(relevant_posts),
        "sent" if email_sent else "FAILED",
    )

    if not email_sent:
        sys.exit(1)


if __name__ == "__main__":
    main()
