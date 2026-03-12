"""Unit tests for helpers.py — parse_editor_name() and name_variants()."""
import pytest
from helpers import parse_editor_name


class TestParseEditorName:
    """Tests for the shared name-parsing utility."""

    def test_simple_two_part_name(self):
        assert parse_editor_name("Kazuhiko Yamamoto") == ("Kazuhiko", "Yamamoto")

    def test_three_part_name(self):
        assert parse_editor_name("Jane Mary Smith") == ("Jane Mary", "Smith")

    def test_single_name(self):
        assert parse_editor_name("Alice") == ("Alice", "")

    def test_strips_dr_title(self):
        assert parse_editor_name("Dr. Jane Smith") == ("Jane", "Smith")

    def test_strips_prof_title(self):
        assert parse_editor_name("Prof. John Doe") == ("John", "Doe")

    def test_strips_professor_title(self):
        assert parse_editor_name("Professor Kazuhiko Yamamoto") == ("Kazuhiko", "Yamamoto")

    def test_strips_multiple_titles(self):
        assert parse_editor_name("Prof. Dr. Maria Garcia") == ("Maria", "Garcia")

    def test_strips_mr_title(self):
        assert parse_editor_name("Mr. Bob Jones") == ("Bob", "Jones")

    def test_strips_phd(self):
        assert parse_editor_name("PhD Alice Brown") == ("Alice", "Brown")

    def test_empty_string(self):
        assert parse_editor_name("") == ("", "")

    def test_only_title(self):
        # Edge case: if name is just a title, return it as-is
        assert parse_editor_name("Dr.") == ("Dr.", "")

    def test_preserves_middle_names(self):
        assert parse_editor_name("Ana Maria Lopez Cruz") == ("Ana Maria Lopez", "Cruz")

    def test_whitespace_handling(self):
        assert parse_editor_name("  Dr.  Jane   Smith  ") == ("Jane", "Smith")


# Also test _name_variants from SnappAgent (it's a staticmethod)
from snapp_agent import SnappAgent


class TestNameVariants:
    """Tests for editor search name variant generation."""

    def test_simple_name_generates_variants(self):
        variants = SnappAgent._name_variants("John Smith")
        assert "John Smith" in variants
        assert "Smith, John" in variants
        assert "Smith John" in variants
        assert "Smith" in variants

    def test_name_with_title(self):
        variants = SnappAgent._name_variants("Dr. Jane Smith")
        assert "Dr. Jane Smith" in variants
        assert "Jane Smith" in variants
        assert "Smith, Jane" in variants

    def test_single_name(self):
        variants = SnappAgent._name_variants("Alice")
        assert "Alice" in variants

    def test_no_duplicates(self):
        variants = SnappAgent._name_variants("John Smith")
        assert len(variants) == len(set(variants))
