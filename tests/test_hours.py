# tests/test_hours.py — Unit tests para logica de horarios de atencion

import pytest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Helpers para mockear get_config()
# ---------------------------------------------------------------------------

def _config(slots=None, tz_offset=None):
    c = {"business": {}, "timezone": {}}
    if slots is not None:
        c["business"]["hours_slots"] = slots
    if tz_offset is not None:
        c["timezone"]["tz_offset"] = tz_offset
    return c


def _slots_only_hours(*hours):
    """Retorna lista de 24 bools con True solo en las horas indicadas."""
    return [i in hours for i in range(24)]


# ---------------------------------------------------------------------------
# Tests: get_hours_slots
# ---------------------------------------------------------------------------

class TestGetHoursSlots:
    def test_valid_slots_returned_as_is(self):
        from agent.config_loader import get_hours_slots
        slots = [True] * 24
        with patch("agent.config_loader.get_config", return_value=_config(slots=slots)):
            assert get_hours_slots() == slots

    def test_missing_slots_returns_all_true(self):
        from agent.config_loader import get_hours_slots
        with patch("agent.config_loader.get_config", return_value=_config()):
            result = get_hours_slots()
            assert result == [True] * 24

    def test_none_slots_returns_all_true(self):
        from agent.config_loader import get_hours_slots
        with patch("agent.config_loader.get_config", return_value=_config(slots=None)):
            assert get_hours_slots() == [True] * 24

    def test_wrong_length_slots_returns_all_true(self):
        from agent.config_loader import get_hours_slots
        with patch("agent.config_loader.get_config", return_value=_config(slots=[True] * 10)):
            assert get_hours_slots() == [True] * 24

    def test_non_bool_values_returns_all_true(self):
        from agent.config_loader import get_hours_slots
        bad_slots = [1] * 24  # ints, not bools
        with patch("agent.config_loader.get_config", return_value=_config(slots=bad_slots)):
            assert get_hours_slots() == [True] * 24

    def test_all_false_slots_valid(self):
        from agent.config_loader import get_hours_slots
        slots = [False] * 24
        with patch("agent.config_loader.get_config", return_value=_config(slots=slots)):
            assert get_hours_slots() == [False] * 24


# ---------------------------------------------------------------------------
# Tests: is_within_business_hours
# ---------------------------------------------------------------------------

class TestIsWithinBusinessHours:
    def _mock_now(self, hour, tz_offset):
        """Retorna un datetime con la hora indicada en la tz indicada."""
        tz = timezone(timedelta(hours=tz_offset))
        return datetime(2024, 6, 15, hour, 30, 0, tzinfo=tz)

    def test_enabled_hour_returns_true(self):
        from agent.config_loader import is_within_business_hours
        slots = _slots_only_hours(9, 10, 11, 12, 13, 14, 15, 16, 17)
        cfg = _config(slots=slots, tz_offset=-3)
        fake_now = self._mock_now(10, -3)
        with patch("agent.config_loader.get_config", return_value=cfg), \
             patch("agent.config_loader.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert is_within_business_hours() is True

    def test_disabled_hour_returns_false(self):
        from agent.config_loader import is_within_business_hours
        slots = _slots_only_hours(9, 10, 11, 12, 13, 14, 15, 16, 17)
        cfg = _config(slots=slots, tz_offset=-3)
        fake_now = self._mock_now(22, -3)
        with patch("agent.config_loader.get_config", return_value=cfg), \
             patch("agent.config_loader.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert is_within_business_hours() is False

    def test_all_false_never_enabled(self):
        from agent.config_loader import is_within_business_hours
        slots = [False] * 24
        cfg = _config(slots=slots, tz_offset=0)
        fake_now = self._mock_now(12, 0)
        with patch("agent.config_loader.get_config", return_value=cfg), \
             patch("agent.config_loader.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert is_within_business_hours() is False

    def test_missing_slots_always_enabled(self):
        from agent.config_loader import is_within_business_hours
        cfg = _config(tz_offset=-3)  # no hours_slots
        fake_now = self._mock_now(3, -3)  # 3am
        with patch("agent.config_loader.get_config", return_value=cfg), \
             patch("agent.config_loader.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert is_within_business_hours() is True

    def test_tz_offset_applied_correctly(self):
        """Con tz_offset=+5 a las 14:00 UTC deberia verse como 19:00 local."""
        from agent.config_loader import is_within_business_hours
        # Solo la hora 19 habilitada
        slots = _slots_only_hours(19)
        cfg = _config(slots=slots, tz_offset=5)
        # datetime local resultante = UTC+5 -> hora 19
        fake_now = self._mock_now(19, 5)
        with patch("agent.config_loader.get_config", return_value=cfg), \
             patch("agent.config_loader.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert is_within_business_hours() is True

    def test_boundary_hour_0(self):
        from agent.config_loader import is_within_business_hours
        slots = _slots_only_hours(0)
        cfg = _config(slots=slots, tz_offset=0)
        fake_now = self._mock_now(0, 0)
        with patch("agent.config_loader.get_config", return_value=cfg), \
             patch("agent.config_loader.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert is_within_business_hours() is True

    def test_boundary_hour_23(self):
        from agent.config_loader import is_within_business_hours
        slots = _slots_only_hours(23)
        cfg = _config(slots=slots, tz_offset=0)
        fake_now = self._mock_now(23, 0)
        with patch("agent.config_loader.get_config", return_value=cfg), \
             patch("agent.config_loader.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert is_within_business_hours() is True


# ---------------------------------------------------------------------------
# Tests: get_out_of_hours_message
# ---------------------------------------------------------------------------

class TestGetOutOfHoursMessage:
    def test_uses_hours_string_when_available(self):
        from agent.config_loader import get_out_of_hours_message
        cfg = {"business": {"hours": "09:00-18:00"}, "timezone": {}}
        with patch("agent.config_loader.get_config", return_value=cfg):
            msg = get_out_of_hours_message()
            assert "09:00-18:00" in msg

    def test_uses_default_when_hours_empty(self):
        from agent.config_loader import get_out_of_hours_message
        cfg = {"business": {"hours": ""}, "timezone": {}}
        with patch("agent.config_loader.get_config", return_value=cfg):
            msg = get_out_of_hours_message()
            assert "fuera de horario" in msg.lower()

    def test_uses_default_when_hours_missing(self):
        from agent.config_loader import get_out_of_hours_message
        cfg = {"business": {}, "timezone": {}}
        with patch("agent.config_loader.get_config", return_value=cfg):
            msg = get_out_of_hours_message()
            assert "fuera de horario" in msg.lower()
