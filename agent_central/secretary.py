"""
Secretary Q&A logic (Step 3) — RAG over the activity vector index.

Embeds a question, retrieves the top-K activity chunks from the Step 2 vector
index, prompts Claude Haiku with that context, and returns an answer + sources.

Kept separate from the FastAPI endpoint so it's testable without the web layer.
The Anthropic API key is read from the environment at SecretaryClient construction
time (request time), never at module import — a missing key surfaces as a 503 at
the endpoint, not a crash at startup.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 1000

SYSTEM_PROMPT = """You are the Secretary of an AI agent observability system called Agent Central. Your job is to answer questions about what AI agents have been doing, based on activity-log data retrieved for you.

Rules:
1. Use ONLY the activity chunks provided in the context. Do not invent or assume agent activity that isn't in the chunks.
2. If the provided chunks don't contain enough information to answer the question, say so honestly, e.g.: "Based on the activity log, I don't have information about that."
3. Be concise. Lead with a direct answer, then supporting detail.
4. Refer to specific time windows or chunk IDs when relevant.
5. Don't pad your answer with disclaimers or apologies, and don't open with "Based on the provided context..." — just answer the question."""


class SecretaryClient:
    """Thin wrapper around the Anthropic SDK for the Secretary's Q&A calls."""

    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        import anthropic  # imported here so module import never needs a key

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set; the Secretary cannot answer questions. "
                "Set it in the environment and retry."
            )
        self.model = model
        self._client = anthropic.Anthropic(api_key=key)

    def _build_messages(self, question: str, context_chunks: list[dict]) -> list[dict]:
        """Pure: build the Anthropic `messages` payload from question + chunks.

        Each chunk is a VectorIndex.query() result dict (chunk_id, summary,
        metadata, distance). Testable without an API call.
        """
        if context_chunks:
            lines = []
            for chunk in context_chunks:
                cid = chunk.get("chunk_id", "?")
                summary = chunk.get("summary", "")
                lines.append(f"[{cid}] {summary}")
            context_block = "\n".join(lines)
        else:
            context_block = "(No activity log context was retrieved for this question.)"

        user_content = (
            "Activity log context:\n"
            f"{context_block}\n\n"
            f"Question: {question}"
        )
        return [{"role": "user", "content": user_content}]

    def ask(self, question: str, context_chunks: list[dict]) -> dict:
        """Call Claude with the retrieved context; return answer + token usage."""
        messages = self._build_messages(question, context_chunks)
        response = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        answer = response.content[0].text if response.content else ""
        usage = getattr(response, "usage", None)
        return {
            "answer": answer.strip(),
            "model": self.model,
            "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
            "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
        }


def _score_from_distance(distance) -> Optional[float]:
    """Convert a ChromaDB distance to a higher-is-better similarity score.

    NOTE: the vector collection uses Chroma's default L2 space, so this is an
    L2-derived score (1 / (1 + distance)), NOT a true cosine similarity. It's
    monotonic in closeness, which is all the sources list needs.
    """
    if distance is None:
        return None
    try:
        return round(1.0 / (1.0 + float(distance)), 4)
    except (ValueError, TypeError):
        return None


def ask_secretary(question: str, vector_index, embedding_service,
                  secretary_client, top_k: int = 5) -> dict:
    """End-to-end: embed question -> retrieve top-K -> ask Claude -> compose response.

    Returns {answer, sources, model, input_tokens, output_tokens}. If the index
    has no matching chunks, returns a no-data answer WITHOUT calling the LLM.
    """
    embeddings = embedding_service.embed_texts([question])
    q_embedding = embeddings[0] if embeddings else []

    results = vector_index.query(q_embedding, n_results=top_k)
    if not results:
        return {
            "answer": "I don't have any activity log data to answer that yet.",
            "sources": [],
            "model": None,
            "input_tokens": 0,
            "output_tokens": 0,
        }

    llm_response = secretary_client.ask(question, results)

    sources = []
    for r in results:
        meta = r.get("metadata") or {}
        sources.append({
            "chunk_id": r.get("chunk_id"),
            "agent_id": meta.get("agent_id"),
            "window_start": meta.get("window_start"),
            "window_end": meta.get("window_end"),
            "score": _score_from_distance(r.get("distance")),
        })

    return {
        "answer": llm_response["answer"],
        "sources": sources,
        "model": llm_response["model"],
        "input_tokens": llm_response["input_tokens"],
        "output_tokens": llm_response["output_tokens"],
    }
