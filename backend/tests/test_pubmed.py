"""Tests for PubMed literature search service."""

import asyncio
from datetime import date

import pytest
from services.pubmed import (
    search_literature,
    PubMedResult,
    PubMedArticle,
    _build_query,
    _date_filter_params,
)


class TestBuildQuery:
    def test_gene_only(self):
        assert _build_query("BDNF") == "BDNF"

    def test_gene_and_context(self):
        q = _build_query("BDNF", therapeutic_context="Alzheimer's disease")
        assert "BDNF" in q
        assert "Alzheimer" in q

    def test_gene_context_and_type(self):
        q = _build_query("BDNF", "Alzheimer's disease", "regulatory_element")
        assert "BDNF" in q
        assert "Alzheimer" in q
        assert "regulatory element" in q


class TestSearchLiterature:
    def test_returns_pubmed_result(self):
        result = asyncio.run(search_literature("BDNF"))
        assert isinstance(result, PubMedResult)

    def test_known_gene_has_articles(self):
        result = asyncio.run(search_literature("BDNF"))
        assert result.total_count > 0
        assert len(result.articles) > 0

    def test_article_has_fields(self):
        result = asyncio.run(search_literature("BDNF"))
        if result.articles:
            a = result.articles[0]
            assert isinstance(a, PubMedArticle)
            assert a.pmid
            assert a.title

    def test_with_therapeutic_context(self):
        result = asyncio.run(
            search_literature("BDNF", therapeutic_context="Alzheimer's disease")
        )
        assert isinstance(result, PubMedResult)
        assert "Alzheimer" in result.query

    def test_empty_gene_returns_empty(self):
        result = asyncio.run(search_literature(""))
        assert result.articles == []
        assert result.query == ""

    def test_max_results_respected(self):
        result = asyncio.run(search_literature("BRCA1", max_results=3))
        assert len(result.articles) <= 3

    def test_default_post_2025_filter_still_finds_articles(self):
        """The 2025/01/01 default shouldn't silently zero out a well-studied gene."""
        result = asyncio.run(search_literature("BRCA1"))
        assert result.total_count > 0

    def test_disabling_date_filter_finds_at_least_as_many(self):
        filtered = asyncio.run(search_literature("BRCA1", mindate="2025/01/01"))
        unfiltered = asyncio.run(search_literature("BRCA1", mindate=None))
        assert unfiltered.total_count >= filtered.total_count

    def test_narrow_past_range_still_returns_results(self):
        result = asyncio.run(
            search_literature("BRCA1", mindate="2020/01/01", maxdate="2020/12/31")
        )
        assert result.total_count > 0


class TestDateFilterParams:
    def test_default_mindate_disabled_returns_empty(self):
        assert _date_filter_params(None, None) == {}

    def test_explicit_range(self):
        params = _date_filter_params("2025/01/01", "2025/06/30")
        assert params == {
            "datetype": "pdat",
            "mindate": "2025/01/01",
            "maxdate": "2025/06/30",
        }

    def test_maxdate_defaults_to_today_when_unset(self):
        params = _date_filter_params("2025/01/01", None)
        assert params["mindate"] == "2025/01/01"
        assert params["maxdate"] == date.today().strftime("%Y/%m/%d")
        assert params["datetype"] == "pdat"
