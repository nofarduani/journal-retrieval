import json
import os
from datetime import datetime, timedelta, timezone

MEMORY_PATH = "data/memory.json"
PRUNE_DAYS = 90


def _empty_memory():
    return {
        "seen_paper_dois": {},
        "seen_post_uris": {},
        "last_run": None,
    }


def load_memory():
    if not os.path.exists(MEMORY_PATH):
        return _empty_memory()
    with open(MEMORY_PATH) as f:
        data = json.load(f)
    # Migrate from list format to dict format if needed
    if isinstance(data.get("seen_paper_dois"), list):
        now = datetime.now(timezone.utc).isoformat()
        data["seen_paper_dois"] = {doi: now for doi in data["seen_paper_dois"]}
    if isinstance(data.get("seen_post_uris"), list):
        now = datetime.now(timezone.utc).isoformat()
        data["seen_post_uris"] = {uri: now for uri in data["seen_post_uris"]}
    return data


def save_memory(memory):
    os.makedirs(os.path.dirname(MEMORY_PATH), exist_ok=True)
    memory["last_run"] = datetime.now(timezone.utc).isoformat()
    with open(MEMORY_PATH, "w") as f:
        json.dump(memory, f, indent=2)


def is_seen(memory, item_id, item_type="paper"):
    store = memory["seen_paper_dois"] if item_type == "paper" else memory["seen_post_uris"]
    return item_id in store


def mark_seen(memory, item_id, item_type="paper"):
    store = memory["seen_paper_dois"] if item_type == "paper" else memory["seen_post_uris"]
    store[item_id] = datetime.now(timezone.utc).isoformat()


def prune_memory(memory):
    cutoff = datetime.now(timezone.utc) - timedelta(days=PRUNE_DAYS)
    for store_key in ("seen_paper_dois", "seen_post_uris"):
        store = memory[store_key]
        memory[store_key] = {
            k: v for k, v in store.items()
            if datetime.fromisoformat(v) > cutoff
        }
