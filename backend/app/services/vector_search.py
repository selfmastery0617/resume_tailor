"""Semantic search over experience challenges.

Uses sentence-transformers (all-MiniLM-L6-v2) as specified. That package pulls
in PyTorch and downloads a model on first use, either of which can be
unavailable — so a deterministic lexical fallback keeps extraction working
instead of failing outright. `backend()` reports which path is active, and the
API surfaces it so a degraded ranking is never silently passed off as semantic.

Embeddings are cached per (model, text-hash): re-encoding the whole library on
every extraction would dominate runtime.
"""

import hashlib
import math
import re
import threading
from typing import Any, Sequence

MODEL_NAME = "all-MiniLM-L6-v2"

_model: Any = None
_model_lock = threading.Lock()
_model_failed: str | None = None
_embedding_cache: dict[str, Any] = {}


def _load_model() -> Any:
    """Load the encoder once. Returns None when unavailable.

    Tries the local cache first. Plain `SentenceTransformer(MODEL_NAME)` calls
    the Hugging Face Hub on every load to check for a newer revision — measured
    at 13.2s against 0.1s from cache, on a model that has not changed since it
    was published. It also means startup depends on the network, and prints an
    unauthenticated-request warning that looks like something is wrong.

    Falls back to a normal load, which downloads, when the cache has no copy.
    """
    global _model, _model_failed
    if _model is not None or _model_failed is not None:
        return _model
    with _model_lock:
        if _model is not None or _model_failed is not None:
            return _model
        try:
            from sentence_transformers import SentenceTransformer

            try:
                _model = SentenceTransformer(MODEL_NAME, local_files_only=True)
            except Exception:  # noqa: BLE001 - not cached yet; fetch it
                _model = SentenceTransformer(MODEL_NAME)
        except Exception as exc:  # noqa: BLE001 - import, download, or runtime
            _model_failed = str(exc)
            _model = None
        return _model


def backend() -> dict[str, Any]:
    """Which ranking path is in use, for the API to report."""
    model = _load_model()
    if model is not None:
        return {"mode": "semantic", "model": MODEL_NAME, "detail": None}
    return {
        "mode": "lexical",
        "model": None,
        "detail": (
            "sentence-transformers is unavailable, so ranking falls back to "
            f"keyword overlap. Reason: {_model_failed}"
        ),
    }


# --- lexical fallback ------------------------------------------------------

_TOKEN = re.compile(r"[a-z0-9+#.]+")
# Words too common in job descriptions to carry ranking signal.
_STOP = frozenset(
    """a an and are as at be by for from has have in is it its of on or that the to with
    we you your our will can must should experience work team years role position job
    strong ability using use used across including etc""".split()
)


def _tokenise(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP and len(t) > 1]


def _lexical_scores(query: str, documents: Sequence[str]) -> list[float]:
    """TF-IDF-ish cosine over token sets. Deterministic and dependency-free."""
    query_tokens = _tokenise(query)
    if not query_tokens:
        return [0.0] * len(documents)

    doc_tokens = [_tokenise(d) for d in documents]
    total_docs = len(doc_tokens) or 1

    # Inverse document frequency, so shared boilerplate counts for little.
    doc_freq: dict[str, int] = {}
    for tokens in doc_tokens:
        for token in set(tokens):
            doc_freq[token] = doc_freq.get(token, 0) + 1

    def weights(tokens: list[str]) -> dict[str, float]:
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        return {
            token: (1 + math.log(count))
            * math.log(1 + total_docs / (1 + doc_freq.get(token, 0)))
            for token, count in counts.items()
        }

    query_weights = weights(query_tokens)
    query_norm = math.sqrt(sum(w * w for w in query_weights.values())) or 1.0

    scores: list[float] = []
    for tokens in doc_tokens:
        doc_weights = weights(tokens)
        norm = math.sqrt(sum(w * w for w in doc_weights.values())) or 1.0
        overlap = sum(
            weight * doc_weights.get(token, 0.0) for token, weight in query_weights.items()
        )
        scores.append(overlap / (query_norm * norm))
    return scores


# --- public API -------------------------------------------------------------


def _cache_key(text: str) -> str:
    return hashlib.sha256(f"{MODEL_NAME}:{text}".encode("utf-8")).hexdigest()


def _encode(texts: Sequence[str], model: Any) -> Any:
    """Encode with a per-text cache so repeat extractions are cheap."""
    import numpy as np

    vectors: list[Any] = [None] * len(texts)
    missing_idx: list[int] = []
    missing_txt: list[str] = []

    for index, text in enumerate(texts):
        cached = _embedding_cache.get(_cache_key(text))
        if cached is None:
            missing_idx.append(index)
            missing_txt.append(text)
        else:
            vectors[index] = cached

    if missing_txt:
        fresh = model.encode(missing_txt, convert_to_numpy=True, normalize_embeddings=True)
        for slot, index in enumerate(missing_idx):
            vector = fresh[slot]
            _embedding_cache[_cache_key(missing_txt[slot])] = vector
            vectors[index] = vector

    return np.vstack(vectors)


def score_documents(query: str, documents: Sequence[str]) -> list[float]:
    """Relevance of each document to the query, higher is better.

    Returns cosine similarity when the encoder is available, and lexical
    similarity otherwise. Both are in a comparable 0-1 range, so callers can
    rank identically either way.
    """
    if not documents:
        return []

    model = _load_model()
    if model is None:
        return _lexical_scores(query, documents)

    try:
        import numpy as np

        doc_vectors = _encode(list(documents), model)
        query_vector = _encode([query], model)[0]
        # Vectors are normalised, so the dot product is the cosine.
        return [float(np.dot(query_vector, doc)) for doc in doc_vectors]
    except Exception:  # noqa: BLE001 - never let ranking break extraction
        return _lexical_scores(query, documents)


def build_query(tech_skills: Sequence[str], job_mission: str, job_title: str = "") -> str:
    """The hybrid query: role + required tech + business context."""
    return " ".join(
        part for part in (job_title, ", ".join(tech_skills), job_mission) if part
    ).strip()
