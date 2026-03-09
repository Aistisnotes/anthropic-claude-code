"""Tests for ingredient extraction logic."""

from __future__ import annotations


from pain_point_analyzer.analyzer.ingredient_extractor import (
    Ingredient,
    merge_ingredients,
)


class TestMergeIngredients:
    def test_dedup_by_name(self):
        auto = [
            Ingredient(name="Aged Garlic Extract", amount="600", unit="mg", sources=["supplement_facts"]),
            Ingredient(name="Vitamin D3", amount="25", unit="mcg", sources=["supplement_facts"]),
        ]
        manual = [
            Ingredient(name="Aged Garlic Extract", amount="600", unit="mg", sources=["user_input"]),
            Ingredient(name="Vitamin K2", amount="100", unit="mcg", sources=["user_input"]),
        ]

        merged = merge_ingredients(auto, manual)
        assert len(merged) == 3

        # Check that AGE has both sources
        age = next(i for i in merged if "garlic" in i.name.lower())
        assert "supplement_facts" in age.sources
        assert "user_input" in age.sources

    def test_empty_inputs(self):
        assert merge_ingredients([], []) == []

    def test_amount_fill_from_manual(self):
        auto = [Ingredient(name="Zinc", sources=["body_copy"])]
        manual = [Ingredient(name="Zinc", amount="30", unit="mg", sources=["user_input"])]

        merged = merge_ingredients(auto, manual)
        assert len(merged) == 1
        assert merged[0].amount == "30"
        assert merged[0].unit == "mg"

    def test_key_normalization(self):
        """Test that keys are normalized (case insensitive, no special chars)."""
        i1 = Ingredient(name="S-allylcysteine", sources=["a"])
        i2 = Ingredient(name="S Allylcysteine", sources=["b"])
        # These should NOT merge because their keys differ
        # (one has hyphen stripped, other has space stripped — both become "sallylcysteine")
        merged = merge_ingredients([i1], [i2])
        assert len(merged) == 1  # they should merge
