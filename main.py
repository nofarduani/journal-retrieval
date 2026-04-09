"""Weekly Research Digest Agent — local orchestrator.

When run as a Claude Code scheduled task, the task prompt orchestrates
the three phases directly (with subagent filtering in Phase 2).
This script exists for local testing — it runs Phase 1 and Phase 3,
skipping AI filtering.
"""

import logging
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    # Phase 1: Fetch and prepare candidates
    logger.info("=== PHASE 1: Fetch & Prepare ===")
    result = subprocess.run([sys.executable, "fetch_and_prepare.py"])
    if result.returncode == 2:
        logger.info("No candidates to filter. Running Phase 3 for cleanup.")
    elif result.returncode != 0:
        logger.error("Phase 1 failed with exit code %d", result.returncode)
        sys.exit(1)
    else:
        logger.info("=== PHASE 2: Filtering ===")
        logger.info("Skipped — AI filtering runs via Claude Code scheduled task subagents.")
        logger.info("All candidates will pass through unfiltered.")

    # Phase 3: Send digest and finalize
    logger.info("=== PHASE 3: Send & Finalize ===")
    result = subprocess.run([sys.executable, "send_and_finalize.py"])
    if result.returncode != 0:
        logger.error("Phase 3 failed with exit code %d", result.returncode)
        sys.exit(1)

    logger.info("=== ALL PHASES COMPLETE ===")


if __name__ == "__main__":
    main()
