"""Tests for Gemini-backed literature detail synthesis."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from config import settings
from services.evidence_synthesis import (
    gemini_available,
    synthesize_detail,
)
from services.pubmed import PubMedArticle


def _article(abstract: str = "A concise finding about this gene.", title: str = "A study") -> PubMedArticle:
    return PubMedArticle(
        pmid="12345678",
        title=title,
        authors=["Smith J"],
        abstract=abstract,
        year="2025",
        journal="Nature Genetics",
    )


@pytest.fixture(autouse=True)
def _reset_gemini_key(monkeypatch):
    """Every test controls its own key state explicitly."""
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    yield


class TestFallbackPath:
    """No key configured (or the live call fails) -> truncated abstract."""

    def test_no_key_means_unavailable(self):
        assert gemini_available() is False

    def test_short_abstract_returned_verbatim(self):
        article = _article(abstract="A concise finding about this gene.")
        result = asyncio.run(synthesize_detail(article))
        assert result == "A concise finding about this gene."

    def test_long_abstract_is_truncated(self):
        long_abstract = "This gene has been studied extensively. " * 20
        article = _article(abstract=long_abstract)
        result = asyncio.run(synthesize_detail(article))
        assert result.endswith("…")
        assert len(result) < len(long_abstract)
        assert result != long_abstract

    def test_no_abstract_falls_back_to_title(self):
        article = _article(abstract="", title="BRCA1 variant functional study")
        result = asyncio.run(synthesize_detail(article))
        assert "BRCA1 variant functional study" in result
        assert "2025" in result

    def test_never_raises_on_gemini_transport_failure(self, monkeypatch):
        monkeypatch.setattr(settings, "gemini_api_key", "fake-test-key")
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectTimeout("boom"))

        with patch("services.evidence_synthesis.httpx.AsyncClient", return_value=mock_client):
            article = _article(abstract="Fallback text should win here.")
            result = asyncio.run(synthesize_detail(article, gene="BRCA1"))

        assert result == "Fallback text should win here."

    def test_truncated_max_tokens_response_falls_back(self, monkeypatch):
        """A MAX_TOKENS finishReason means a cut-off sentence fragment, not a
        usable summary — must degrade to the honest fallback, not surface the
        fragment (regression test for the gemini-2.5 thinking-budget bug)."""
        monkeypatch.setattr(settings, "gemini_api_key", "fake-test-key")
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "candidates": [{
                "finishReason": "MAX_TOKENS",
                "content": {"parts": [{"text": "In BRCA1-deficient cells"}]},
            }]
        }

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("services.evidence_synthesis.httpx.AsyncClient", return_value=mock_client):
            article = _article(abstract="Fallback text should win over the fragment.")
            result = asyncio.run(synthesize_detail(article))

        assert result == "Fallback text should win over the fragment."

    def test_never_raises_on_malformed_response(self, monkeypatch):
        monkeypatch.setattr(settings, "gemini_api_key", "fake-test-key")
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"unexpected": "shape"}

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("services.evidence_synthesis.httpx.AsyncClient", return_value=mock_client):
            article = _article(abstract="Fallback text on bad shape.")
            result = asyncio.run(synthesize_detail(article))

        assert result == "Fallback text on bad shape."


class TestGeminiSuccessPath:
    """Key configured and Gemini responds -> its summary is used verbatim."""

    def test_calls_gemini_and_returns_its_text(self, monkeypatch):
        monkeypatch.setattr(settings, "gemini_api_key", "fake-test-key")
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"text": "  This paper reports BRCA1 splicing effects in vitro.  "}]}}
            ]
        }

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("services.evidence_synthesis.httpx.AsyncClient", return_value=mock_client):
            article = _article(abstract="A much longer raw abstract that Gemini condenses.")
            result = asyncio.run(synthesize_detail(article, gene="BRCA1", label="exon 11"))

        assert result == "This paper reports BRCA1 splicing effects in vitro."
        # Sent the real abstract/gene context to Gemini, not a canned prompt.
        sent_payload = mock_client.post.call_args.kwargs["json"]
        prompt_text = sent_payload["contents"][0]["parts"][0]["text"]
        assert "BRCA1" in prompt_text
        assert "exon 11" in prompt_text
        assert "A much longer raw abstract" in prompt_text

    def test_uses_api_key_header_not_query_param(self, monkeypatch):
        monkeypatch.setattr(settings, "gemini_api_key", "fake-test-key")
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Summary."}]}}]
        }

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("services.evidence_synthesis.httpx.AsyncClient", return_value=mock_client):
            asyncio.run(synthesize_detail(_article()))

        sent_headers = mock_client.post.call_args.kwargs["headers"]
        assert sent_headers["x-goog-api-key"] == "fake-test-key"
