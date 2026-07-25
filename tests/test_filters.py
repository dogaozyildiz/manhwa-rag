"""Tests for structured-filter extraction and query routing.

These matter more than they look. A missed filter does not error — it silently
returns results that violate what the user asked for, which is the exact
failure this project exists to avoid.
"""

import pytest

from app.retrieval.filters import extract_filters, strip_filter_terms
from app.retrieval.router import route_query


class TestOrigin:
    @pytest.mark.parametrize(
        "query,expected",
        [
            ("completed manhwa", "KR"),
            ("korean series", "KR"),
            ("japanese manga", "JP"),
            ("chinese manhua", "CN"),
        ],
    )
    def test_medium_word_implies_country(self, query, expected):
        assert extract_filters(query).country == expected

    def test_webtoon_alone_is_not_an_origin_filter(self):
        """'webtoon' is a format and a platform name used generically, so
        treating it as an origin marker attaches a Korea filter to general
        industry questions like 'what is a webtoon?'."""
        assert extract_filters("what is a webtoon").country is None


class TestChapterRanges:
    @pytest.mark.parametrize(
        "query,lo,hi",
        [
            ("under 100 chapters", None, 100),
            ("fewer than 50 chapters", None, 50),
            ("more than 200 chapters", 200, None),
            ("at least 30 chapters", 30, None),
            ("between 50 and 150 chapters", 50, 150),
            ("between 150 and 50 chapters", 50, 150),  # reversed input
        ],
    )
    def test_ranges(self, query, lo, hi):
        f = extract_filters(query)
        assert (f.min_chapters, f.max_chapters) == (lo, hi)

    def test_comparison_without_a_unit_is_not_a_chapter_filter(self):
        """'rated above 85' is a score, not a chapter count. Treating a bare
        comparison as chapters invents a constraint the user never gave."""
        f = extract_filters("manhwa rated above 85")
        assert f.max_chapters is None and f.min_chapters is None
        assert f.min_score == 85


class TestStatusAndYear:
    @pytest.mark.parametrize(
        "query,status",
        [("completed series", "FINISHED"), ("ongoing series", "RELEASING"),
         ("cancelled series", "CANCELLED"), ("series on hiatus", "HIATUS")],
    )
    def test_status(self, query, status):
        assert extract_filters(query).status == status

    def test_before_year(self):
        assert extract_filters("manhwa before 2020").max_year == 2020

    def test_after_year(self):
        assert extract_filters("manhwa since 2015").min_year == 2015


class TestGenres:
    def test_canonical_genre(self):
        assert "Romance" in extract_filters("romance manhwa").genres

    def test_synonym_maps_to_canonical(self):
        assert "Sci-Fi" in extract_filters("science fiction manga").genres

    def test_exclusion_does_not_also_include(self):
        """'no romance' must not register Romance as both wanted and unwanted."""
        f = extract_filters("action manhwa with no romance")
        assert "Romance" in f.exclude_genres
        assert "Romance" not in f.genres
        assert "Action" in f.genres

    def test_score_on_ten_scale_is_rescaled(self):
        assert extract_filters("series rated 8").min_score == 80


class TestSemanticRemainder:
    def test_constraints_are_stripped_leaving_intent(self):
        remainder = strip_filter_terms(
            "completed romance manhwa under 100 chapters like Solo Leveling"
        )
        assert "Solo Leveling" in remainder
        for term in ("completed", "romance", "manhwa", "100", "chapters"):
            assert term not in remainder.lower()

    def test_pure_filter_query_leaves_nothing(self):
        """An empty remainder is a valid outcome, not a bug — it means the query
        was entirely structured, and ranking falls back to popularity."""
        assert strip_filter_terms("completed romance manhwa") == ""

    def test_industry_question_is_left_intact(self):
        assert "webtoon" in strip_filter_terms("what is a webtoon").lower()


class TestRouting:
    @pytest.mark.parametrize(
        "query,route",
        [
            ("completed romance manhwa under 100 chapters", "catalogue"),
            ("recommend something like Solo Leveling", "catalogue"),
            ("how does Naver Webtoon make money", "industry"),
            ("what is a webtoon", "industry"),
            ("do manhwa run longer than manga and why", "both"),
        ],
    )
    def test_routes(self, query, route):
        assert route_query(query, extract_filters(query)) == route

    def test_hard_filters_force_catalogue(self):
        q = "ongoing fantasy manhwa with more than 200 chapters"
        assert route_query(q, extract_filters(q)) == "catalogue"
