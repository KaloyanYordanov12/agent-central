"""Phase 1: clean rebuild of the Secretary vector index from the CURRENT
activity.db, so retrieval and the activity_log are one consistent system of record.

The deployed index (data/chroma) was tracking events that were archived during an
earlier DB archival (index_state had last_indexed_event_id far past the current
row count), so the live Secretary retrieved stale/archived windows that no longer
verify against data/activity.db. This drops the old collection (derived,
gitignored data) and re-indexes only the current activity.db. It never touches
activity.db or any activity-archive-*.db. $0: uses the local embedding model only.
"""
import os

from agent_central import activity_log, indexer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, "data", "activity.db")
CHROMA = os.path.join(ROOT, "data", "chroma")
STATE = os.path.join(ROOT, "data", "index_state.json")

activity_log.init_db(DB)

# Drop the stale collection (removes archived-only windows) so the rebuild is clean.
try:
    before = indexer.VectorIndex(CHROMA).count()
    indexer.VectorIndex(CHROMA).delete_collection()
    print(f"dropped stale collection (had {before} chunks)")
except Exception as e:
    print("no existing collection to drop:", e)

# Fresh index state (id 0) so run_index_pass re-reads ALL current events.
state = indexer.IndexState(path=STATE)
emb = indexer.EmbeddingService()
stats = indexer.run_index_pass(DB, CHROMA, emb, state)
print("rebuild stats:", stats)
print("new chunk count:", indexer.VectorIndex(CHROMA).count())
