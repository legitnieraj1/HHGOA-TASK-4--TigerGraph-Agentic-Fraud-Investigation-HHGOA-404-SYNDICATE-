"""Local embedding model (singleton, lazy-loaded): all-MiniLM-L6-v2, 384-dim, matches tigergraph/spec.py EMB_DIM.
No API cost, no network dependency at embed time -- fits `.env`'s EMBEDDING_PROVIDER=local."""
import functools


@functools.lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")


def embed(texts):
    """texts: str or list[str]. Returns list[list[float]] (or a single list[float] for a single string)."""
    single = isinstance(texts, str)
    if single:
        texts = [texts]
    vecs = _model().encode(list(texts), normalize_embeddings=True).tolist()
    return vecs[0] if single else vecs
