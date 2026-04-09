"""Bluesky client for fetching posts from AT Protocol accounts."""

import logging
import time
from datetime import datetime, timedelta, timezone

from atproto import Client, models

import config

logger = logging.getLogger(__name__)


def create_client() -> Client:
    """Create and authenticate a Bluesky AT Protocol client.

    Returns:
        An authenticated Client instance.
    """
    client = Client()
    client.login(config.BLUESKY_HANDLE, config.BLUESKY_APP_PASSWORD)
    logger.info("Authenticated as %s", config.BLUESKY_HANDLE)
    return client


def fetch_posts_from_accounts(
    client: Client,
    accounts: list[dict],
    days: int,
) -> list[dict]:
    """Fetch recent posts from a list of Bluesky accounts.

    Args:
        client: An authenticated atproto Client.
        accounts: List of dicts with keys: did, handle, display_name.
        days: Only include posts created within this many days.

    Returns:
        List of post dicts with keys: uri, author_handle, author_name,
        text, created_at, url.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts: list[dict] = []

    for account in accounts:
        did = account["did"]
        handle = account.get("handle", did)
        display_name = account.get("display_name", handle)

        try:
            account_posts = _fetch_account_posts(
                client, did, handle, display_name, cutoff
            )
            all_posts.extend(account_posts)
        except Exception:
            logger.warning(
                "Failed to fetch posts for %s (%s), skipping",
                handle,
                did,
                exc_info=True,
            )

    logger.info(
        "Fetched %d posts from %d accounts (last %d days)",
        len(all_posts),
        len(accounts),
        days,
    )
    return all_posts


def _fetch_account_posts(
    client: Client,
    did: str,
    handle: str,
    display_name: str,
    cutoff: datetime,
) -> list[dict]:
    """Fetch and filter posts for a single account, with pagination.

    Paginates through the author feed until posts are older than the cutoff
    or there are no more pages. Skips reposts. Retries on network errors.

    Returns:
        List of post dicts for this account.
    """
    posts: list[dict] = []
    cursor: str | None = None
    reached_cutoff = False

    while not reached_cutoff:
        response = _get_author_feed_with_retry(
            client, did, cursor=cursor, limit=50
        )

        for feed_item in response.feed:
            # Skip reposts (reason field indicates a repost)
            if feed_item.reason and isinstance(
                feed_item.reason, models.AppBskyFeedDefs.ReasonRepost
            ):
                continue

            post_view = feed_item.post
            record = post_view.record

            # Parse the created_at timestamp from the post record
            created_at_str = getattr(record, "created_at", None)
            if not created_at_str:
                continue

            created_at = _parse_datetime(created_at_str)
            if created_at is None:
                continue

            # Stop paginating if we've gone past the cutoff
            if created_at < cutoff:
                reached_cutoff = True
                break

            text = getattr(record, "text", "") or ""
            uri = post_view.uri

            # Extract rkey from AT URI: at://did:plc:xxx/app.bsky.feed.post/rkey
            rkey = uri.rsplit("/", 1)[-1] if "/" in uri else uri
            url = f"https://bsky.app/profile/{handle}/post/{rkey}"

            posts.append(
                {
                    "uri": uri,
                    "author_handle": handle,
                    "author_name": display_name,
                    "text": text,
                    "created_at": created_at_str
                    if isinstance(created_at_str, str)
                    else str(created_at_str),
                    "url": url,
                }
            )

        # Check for next page
        cursor = response.cursor
        if not cursor:
            break

        # Rate limit between pagination requests
        time.sleep(0.1)

    return posts


def _get_author_feed_with_retry(
    client: Client,
    actor: str,
    cursor: str | None = None,
    limit: int = 50,
    max_retries: int = 3,
    backoff: float = 1.0,
) -> "models.AppBskyFeedGetAuthorFeed.Response":
    """Call get_author_feed with retry logic for network errors."""
    for attempt in range(max_retries):
        try:
            return client.get_author_feed(
                actor=actor, cursor=cursor, limit=limit
            )
        except Exception as exc:
            if attempt < max_retries - 1:
                logger.warning(
                    "get_author_feed attempt %d/%d failed for %s: %s",
                    attempt + 1,
                    max_retries,
                    actor,
                    exc,
                )
                time.sleep(backoff * (attempt + 1))
            else:
                raise


def _parse_datetime(value) -> datetime | None:
    """Parse a datetime value from the atproto SDK.

    The SDK may return the created_at field as a string or a datetime object.
    Handles both cases gracefully.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    if isinstance(value, str):
        # Try ISO 8601 formats
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f+00:00",
            "%Y-%m-%dT%H:%M:%S+00:00",
        ):
            try:
                dt = datetime.strptime(value, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        # Fallback: fromisoformat (Python 3.11+ handles Z suffix)
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            logger.warning("Unable to parse datetime: %s", value)
            return None

    logger.warning("Unexpected datetime type %s: %s", type(value), value)
    return None
