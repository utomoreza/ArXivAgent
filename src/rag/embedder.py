"""Sentence embedding wrapper for the RAG pipeline.

Loads ``BAAI/bge-small-en-v1.5`` (384 dimensions) once at module level so all
callers share one in-process model instance. Embeddings are L2-normalised,
making cosine similarity equivalent to dot product for pgvector queries.
"""

import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("BAAI/bge-small-en-v1.5")


def embed(texts: list[str]) -> np.ndarray:
    """Embed a batch of texts and return L2-normalised vectors.

    Args:
        texts: One or more strings to embed.

    Returns:
        Float32 numpy array of shape ``(len(texts), 384)`` with unit-norm rows.
    """
    return model.encode(inputs=texts, normalize_embeddings=True, batch_size=64)
