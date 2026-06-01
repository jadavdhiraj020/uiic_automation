import pytest
from unittest.mock import patch
from app.portals.oic.automation.ui_utils import _get_oic_fill_settings


def test_get_oic_fill_settings_defaults():
    # Test fallback/default values when load_automation_defaults is mock-returned
    with patch("app.utils.load_automation_defaults") as mock_defaults:
        mock_defaults.return_value = {
            "instant_fill": "Yes",
            "typing_delay_ms": "30"
        }
        
        instant_fill, typing_delay = _get_oic_fill_settings()
        assert instant_fill is True
        assert typing_delay == 30


def test_get_oic_fill_settings_typed_mode():
    # Test when instant fill is disabled (No)
    with patch("app.utils.load_automation_defaults") as mock_defaults:
        mock_defaults.return_value = {
            "instant_fill": "No",
            "typing_delay_ms": "15"
        }
        
        instant_fill, typing_delay = _get_oic_fill_settings()
        assert instant_fill is False
        assert typing_delay == 15


def test_get_oic_fill_settings_invalid_delay_fallback():
    # Test invalid typing delay fallback
    with patch("app.utils.load_automation_defaults") as mock_defaults:
        mock_defaults.return_value = {
            "instant_fill": "No",
            "typing_delay_ms": "invalid_number"
        }
        
        instant_fill, typing_delay = _get_oic_fill_settings()
        assert instant_fill is False
        assert typing_delay == 25  # default fallback
