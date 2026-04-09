"""Build and cache a Bluesky social graph (1st and 2nd degree connections)."""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from atproto import Client

import config

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
GRAPH_PATH = DATA_DIR / "social_graph.json"


def build_or_refresh_graph(
    client: Client,
    handle: str,
    force: bool = False,
) -> dict:
    """Build or refresh the social graph for the given handle.

    Loads a cached graph if it exists and is fresh (less than
    config.GRAPH_REFRESH_DAYS old). Otherwise, rebuilds the graph by
    crawling 1st and 2nd degree connections.

    Args:
        client: An authenticated atproto Client.
        handle: The Bluesky handle to build the graph around.
        force: If True, rebuild even if the cache is fresh.

    Returns:
        A dict with keys: last_refreshed, handle, first_degree, second_degree.
    """
    if not force:
        cached = _load_cached_graph()
        if cached is not None:
            logger.info(
                "Using cached social graph (refreshed %s)",
                cached.get("last_refreshed"),
            )
            return cached

    logger.info("Building social graph for %s...", handle)

    # --- Collect 1st degree connections ---
    first_degree_map: dict[str, dict] = {}

    logger.info("Fetching follows for %s...", handle)
    follows = _paginate_follows(client, handle)
    for profile in follows:
        did = profile.did
        first_degree_map[did] = {
            "did": did,
            "handle": profile.handle,
            "display_name": profile.display_name or "",
        }

    logger.info("Fetching followers for %s...", handle)
    followers = _paginate_followers(client, handle)
    for profile in followers:
        did = profile.did
        if did not in first_degree_map:
            first_degree_map[did] = {
                "did": did,
                "handle": profile.handle,
                "display_name": profile.display_name or "",
            }

    first_degree_list = list(first_degree_map.values())
    first_degree_dids = set(first_degree_map.keys())
    logger.info("Found %d unique 1st degree connections", len(first_degree_dids))

    # --- Collect 2nd degree connections ---
    second_degree_counts: dict[str, dict] = {}
    # Maps DID -> {did, handle, display_name, count}

    try:
        for i, account in enumerate(first_degree_list):
            if (i + 1) % 50 == 0 or i == 0:
                logger.info(
                    "Processing 2nd degree: %d/%d accounts...",
                    i + 1,
                    len(first_degree_list),
                )

            try:
                their_follows = _paginate_follows(client, account["did"])
            except Exception:
                logger.warning(
                    "Failed to get follows for %s (%s), skipping",
                    account["handle"],
                    account["did"],
                    exc_info=True,
                )
                continue

            for profile in their_follows:
                did = profile.did

                # Skip accounts already in 1st degree set
                if did in first_degree_dids:
                    continue

                if did in second_degree_counts:
                    second_degree_counts[did]["count"] += 1
                else:
                    second_degree_counts[did] = {
                        "did": did,
                        "handle": profile.handle,
                        "display_name": profile.display_name or "",
                        "count": 1,
                    }

            # Rate limit between accounts
            time.sleep(0.2)

    except Exception:
        logger.error(
            "2nd degree crawl failed after %d accounts; saving partial graph",
            i + 1,
            exc_info=True,
        )

    # Sort by occurrence count descending, cap at configured limit
    sorted_second = sorted(
        second_degree_counts.values(),
        key=lambda x: x["count"],
        reverse=True,
    )[: config.SECOND_DEGREE_CAP]

    second_degree_list = [
        {
            "did": entry["did"],
            "handle": entry["handle"],
            "display_name": entry["display_name"],
            "network_score": entry["count"],
        }
        for entry in sorted_second
    ]

    logger.info(
        "Found %d 2nd degree connections (capped at %d)",
        len(second_degree_counts),
        config.SECOND_DEGREE_CAP,
    )

    graph = {
        "last_refreshed": datetime.now(timezone.utc).isoformat(),
        "handle": handle,
        "first_degree": first_degree_list,
        "second_degree": second_degree_list,
    }

    _save_graph(graph)
    return graph


def _load_cached_graph() -> dict | None:
    """Load the social graph from cache if it exists and is fresh.

    Returns the cached graph dict if the file exists and was refreshed
    less than config.GRAPH_REFRESH_DAYS ago. Otherwise returns None.
    """
    if not GRAPH_PATH.exists():
        return None

    try:
        with open(GRAPH_PATH, "r", encoding="utf-8") as f:
            graph = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load cached graph: %s", exc)
        return None

    last_refreshed_str = graph.get("last_refreshed")
    if not last_refreshed_str:
        return None

    try:
        last_refreshed = datetime.fromisoformat(
            last_refreshed_str.replace("Z", "+00:00")
        )
    except ValueError:
        logger.warning("Invalid last_refreshed timestamp: %s", last_refreshed_str)
        return None

    age = datetime.now(timezone.utc) - last_refreshed
    if age > timedelta(days=config.GRAPH_REFRESH_DAYS):
        logger.info(
            "Cached graph is %d days old (limit %d), will rebuild",
            age.days,
            config.GRAPH_REFRESH_DAYS,
        )
        return None

    return graph


def _save_graph(graph: dict) -> None:
    """Save the social graph to data/social_graph.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with open(GRAPH_PATH, "w", encoding="utf-8") as f:
            json.dump(graph, f, indent=2, ensure_ascii=False)
        logger.info("Saved social graph to %s", GRAPH_PATH)
    except OSError as exc:
        logger.error("Failed to save social graph: %s", exc)


def _paginate_follows(client: Client, actor: str) -> list:
    """Paginate through all follows for an actor.

    Returns a list of ProfileView objects.
    """
    all_follows = []
    cursor: str | None = None

    while True:
        response = client.get_follows(actor=actor, cursor=cursor, limit=100)
        all_follows.extend(response.follows)

        cursor = response.cursor
        if not cursor:
            break

        time.sleep(0.1)

    return all_follows


def _paginate_followers(client: Client, actor: str) -> list:
    """Paginate through all followers for an actor.

    Returns a list of ProfileView objects.
    """
    all_followers = []
    cursor: str | None = None

    while True:
        response = client.get_followers(actor=actor, cursor=cursor, limit=100)
        all_followers.extend(response.followers)

        cursor = response.cursor
        if not cursor:
            break

        time.sleep(0.1)

    return all_followers
