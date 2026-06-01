# tests/test_hours.py — is_within_business_hours + get_hours_slots

from unittest.mock import patch

from agent import config_loader


def _mock_cfg(slots=None, tz_offset=-3):
    cfg = {"timezone": {"tz_offset": tz_offset}}
    if slots is not None:
        cfg["business"] = {"hours_slots": slots}
    else:
        cfg["business"] = {"hours": ""}
    return cfg


def test_get_hours_slots_returns_24_bools_when_valid():
    slots = [True] * 24
    slots[3] = False
    with patch.object(config_loader, "get_config", return_value=_mock_cfg(slots=slots)):
        out = config_loader.get_hours_slots()
    assert out == slots
    assert len(out) == 24


def test_get_hours_slots_falls_back_to_all_true_when_missing():
    with patch.object(config_loader, "get_config", return_value={"business": {}}):
        out = config_loader.get_hours_slots()
    assert out == [True] * 24


def test_get_hours_slots_falls_back_when_wrong_length():
    bad = [True] * 12
    with patch.object(config_loader, "get_config", return_value=_mock_cfg(slots=bad)):
        out = config_loader.get_hours_slots()
    assert out == [True] * 24


def test_get_hours_slots_falls_back_when_wrong_type():
    with patch.object(config_loader, "get_config", return_value=_mock_cfg(slots="invalid")):
        out = config_loader.get_hours_slots()
    assert out == [True] * 24


def test_is_within_business_hours_true_when_24_7():
    with patch.object(config_loader, "get_config", return_value=_mock_cfg(slots=[True] * 24)):
        assert config_loader.is_within_business_hours() is True


def test_is_within_business_hours_false_when_all_off():
    with patch.object(config_loader, "get_config", return_value=_mock_cfg(slots=[False] * 24)):
        assert config_loader.is_within_business_hours() is False
