"""Unit tests for src/rag/embedder.py (T036).

All tests mock ``src.rag.embedder.model`` directly so the real SentenceTransformer
model is never called during the test suite (no GPU/download required).
"""

from unittest.mock import MagicMock, patch

import numpy as np

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_embed_returns_numpy_array_with_correct_shape():
    """embed() returns a numpy array of shape (n, 384)."""
    from src.rag.embedder import embed

    mock_model = MagicMock()
    mock_model.encode.return_value = np.zeros((3, 384), dtype=np.float32)

    with patch("src.rag.embedder.model", mock_model):
        result = embed(["text one", "text two", "text three"])

    assert isinstance(result, np.ndarray)
    assert result.shape == (3, 384)


def test_embed_single_text_returns_shape_1_384():
    """embed() with a single string returns shape (1, 384)."""
    from src.rag.embedder import embed

    mock_model = MagicMock()
    mock_model.encode.return_value = np.zeros((1, 384), dtype=np.float32)

    with patch("src.rag.embedder.model", mock_model):
        result = embed(["single text"])

    assert result.shape == (1, 384)


def test_embed_passes_normalize_embeddings_true():
    """embed() passes normalize_embeddings=True to model.encode."""
    from src.rag.embedder import embed

    mock_model = MagicMock()
    mock_model.encode.return_value = np.zeros((1, 384), dtype=np.float32)

    with patch("src.rag.embedder.model", mock_model):
        embed(["text"])

    call_kwargs = mock_model.encode.call_args.kwargs
    assert call_kwargs.get("normalize_embeddings") is True


def test_embed_uses_inputs_keyword_not_sentences():
    """embed() uses the 'inputs=' keyword (not deprecated 'sentences=')."""
    from src.rag.embedder import embed

    mock_model = MagicMock()
    mock_model.encode.return_value = np.zeros((2, 384), dtype=np.float32)
    texts = ["first", "second"]

    with patch("src.rag.embedder.model", mock_model):
        embed(texts)

    call_kwargs = mock_model.encode.call_args.kwargs
    assert "inputs" in call_kwargs, "'inputs' keyword must be used"
    assert "sentences" not in call_kwargs, "'sentences' is deprecated — do not use"
    assert call_kwargs["inputs"] == texts


def test_embed_passes_batch_size_64():
    """embed() passes batch_size=64 to model.encode."""
    from src.rag.embedder import embed

    mock_model = MagicMock()
    mock_model.encode.return_value = np.zeros((1, 384), dtype=np.float32)

    with patch("src.rag.embedder.model", mock_model):
        embed(["text"])

    call_kwargs = mock_model.encode.call_args.kwargs
    assert call_kwargs.get("batch_size") == 64
