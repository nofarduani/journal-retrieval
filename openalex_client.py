"""Fetch recent academic papers from the OpenAlex API.

Rate limits (free tier): 100,000 credits/day, 100 req/s.
List/filter queries cost 10 credits each.
Our ~40 ISSN queries use ~400 credits — well within limits.
"""

import logging
import time
from datetime import datetime, timedelta

import httpx

import config

logger = logging.getLogger(__name__)

# Shared across all requests in a run to track daily budget
_remaining_credits = None


def reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct abstract text from an OpenAlex inverted index.

    OpenAlex stores abstracts as {"word": [pos1, pos2], ...}.
    We flatten to (word, position) tuples, sort by position, and join.
    """
    if inverted_index is None:
        return ""
    words = []
    for word, positions in inverted_index.items():
        for pos in positions:
            words.append((word, pos))
    words.sort(key=lambda x: x[1])
    return " ".join(w for w, _ in words)


def _update_rate_limit_info(response: httpx.Response):
    """Read OpenAlex rate limit headers and log if running low."""
    global _remaining_credits
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining is not None:
        _remaining_credits = int(remaining)
        if _remaining_credits < 1000:
            logger.warning("OpenAlex credits running low: %d remaining", _remaining_credits)


def _fetch_works_for_issn(
    issn: str,
    from_date: str,
    seen_ids: set,
    journal_name: str,
) -> list[dict]:
    """Fetch all works for a single ISSN from a given date, handling pagination and retries."""
    global _remaining_credits

    # Skip if we already know credits are exhausted
    if _remaining_credits is not None and _remaining_credits < 10:
        logger.warning("Skipping ISSN %s — daily credits exhausted (%d remaining)", issn, _remaining_credits)
        return []

    params = {
        "filter": f"primary_location.source.issn:{issn},from_created_date:{from_date}",
        "per_page": 50,
        "select": "id,doi,title,authorships,primary_location,abstract_inverted_index,publication_date",
        "cursor": "*",
    }

    if config.OPENALEX_API_KEY:
        params["api_key"] = config.OPENALEX_API_KEY

    if config.GMAIL_ADDRESS:
        params["mailto"] = config.GMAIL_ADDRESS

    papers = []

    with httpx.Client(timeout=30.0) as client:
        while True:
            response = None
            for attempt in range(4):
                try:
                    response = client.get(
                        "https://api.openalex.org/works", params=params
                    )
                    _update_rate_limit_info(response)

                    if response.status_code == 429:
                        # Use Retry-After header if present, otherwise exponential backoff
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            wait = int(retry_after)
                        else:
                            wait = 2 ** (attempt + 1)  # 2, 4, 8, 16 seconds
                        logger.warning(
                            "Rate limited (429) for ISSN %s, retrying in %ds (attempt %d/4)",
                            issn, wait, attempt + 1,
                        )
                        time.sleep(wait)
                        continue
                    response.raise_for_status()
                    break
                except httpx.HTTPStatusError:
                    if response is not None and response.status_code == 429:
                        continue
                    raise
            else:
                logger.warning(
                    "Failed to fetch ISSN %s after 4 retries (rate limited), skipping", issn,
                )
                return papers

            data = response.json()
            results = data.get("results", [])

            if not results:
                break

            for work in results:
                work_id = work.get("id")
                if work_id in seen_ids:
                    continue
                seen_ids.add(work_id)

                authors = []
                for authorship in work.get("authorships") or []:
                    author = authorship.get("author", {})
                    name = author.get("display_name") if author else None
                    if name:
                        authors.append(name)

                doi = work.get("doi")
                url = doi if doi else work_id

                papers.append(
                    {
                        "id": work_id,
                        "doi": doi,
                        "title": work.get("title"),
                        "authors": authors,
                        "journal": journal_name,
                        "abstract": reconstruct_abstract(
                            work.get("abstract_inverted_index")
                        ),
                        "publication_date": work.get("publication_date"),
                        "url": url,
                    }
                )

            # Check for next page
            meta = data.get("meta", {})
            next_cursor = meta.get("next_cursor")
            if next_cursor is None:
                break
            params["cursor"] = next_cursor
            time.sleep(0.5)

    return papers


def fetch_recent_papers(journals: dict, days: int) -> list[dict]:
    """Fetch recent papers from OpenAlex for the given journals.

    Args:
        journals: Mapping of journal name to list of ISSNs.
        days: Number of days to look back from today.

    Returns:
        List of paper dicts, deduplicated by OpenAlex ID.
    """
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    seen_ids: set = set()
    all_papers: list[dict] = []

    for journal_name, issns in journals.items():
        for issn in issns:
            try:
                papers = _fetch_works_for_issn(issn, from_date, seen_ids, journal_name)
                all_papers.extend(papers)
                logger.info(
                    "Fetched %d new papers for %s (ISSN %s)",
                    len(papers), journal_name, issn,
                )
            except Exception:
                logger.warning(
                    "Failed to fetch papers for %s (ISSN %s), skipping",
                    journal_name, issn, exc_info=True,
                )
            # Polite delay between ISSN queries
            time.sleep(0.5)

    logger.info("Total papers fetched: %d (credits remaining: %s)",
                len(all_papers), _remaining_credits)
    return all_papers
