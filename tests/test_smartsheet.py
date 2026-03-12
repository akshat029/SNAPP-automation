"""Unit tests for smartsheet_reader.py — action mapping and row structuring."""
import pytest
from smartsheet_reader import ACTION_TYPE_MAP


class TestActionTypeMap:
    """Tests for action type mapping from raw Smartsheet values."""

    def test_onboarding_variants(self):
        assert ACTION_TYPE_MAP["on-boarding (only)"] == "onboard"
        assert ACTION_TYPE_MAP["on-boarding"] == "onboard"
        assert ACTION_TYPE_MAP["onboard"] == "onboard"
        assert ACTION_TYPE_MAP["onboarding"] == "onboard"

    def test_offboarding_variants(self):
        assert ACTION_TYPE_MAP["off-boarding"] == "offboard"
        assert ACTION_TYPE_MAP["offboard"] == "offboard"
        assert ACTION_TYPE_MAP["offboarding"] == "offboard"
        assert ACTION_TYPE_MAP["deactivate"] == "offboard"
        assert ACTION_TYPE_MAP["deactivation"] == "offboard"

    def test_update_variants(self):
        assert ACTION_TYPE_MAP["update"] == "update"
        assert ACTION_TYPE_MAP["edit"] == "update"
        assert ACTION_TYPE_MAP["change"] == "update"

    def test_unavailability_variants(self):
        assert ACTION_TYPE_MAP["unavailability"] == "set_unavailability"
        assert ACTION_TYPE_MAP["set unavailability"] == "set_unavailability"

    def test_unknown_action_not_in_map(self):
        assert "random_action" not in ACTION_TYPE_MAP
