import pytest

from server.telemetry import Sample
from server.vibration import Vibration, VibrationModel, levels_line, validate_settings

SETTINGS = {"enabled": True, "strength": 1.0, "game": True, "gears": True, "shift": True,
            "abs": True, "engine": False}


def levels(sample, rumble=(0.0, 0.0), now=10.0, settings=SETTINGS, model=None):
    return (model or VibrationModel()).levels(settings, sample, rumble, now)


def test_game_rumble_goes_to_the_matching_motor_scaled_by_strength():
    assert levels(Sample(rpm=2000), rumble=(0.8, 0.2)) == (0.8, 0.2)
    half = {**SETTINGS, "strength": 0.5}
    assert levels(Sample(rpm=2000), rumble=(0.8, 0.2), settings=half) == (0.4, 0.1)
    off = {**SETTINGS, "game": False}
    assert levels(Sample(rpm=2000), rumble=(0.8, 0.2), settings=off) == (0.0, 0.0)


def test_gear_change_thumps_both_motors_briefly():
    model = VibrationModel()
    assert levels(Sample(gear=2, rpm=3000), model=model, now=10.0) == (0, 0)
    assert levels(Sample(gear=3, rpm=3000), model=model, now=10.05) == (1.0, 1.0)
    assert levels(Sample(gear=3, rpm=3000), model=model, now=10.3) == (0, 0)


def test_shift_point_pulses_and_abs_buzzes():
    redline = Sample(rpm=7000, max_rpm=7200)
    pulses = {levels(redline, now=10 + i / 100)[0] for i in range(20)}
    assert pulses == {0.0, 0.7}
    assert levels(Sample(rpm=3000, lights={"abs": True})) == (0.55, 0.55)
    quiet = {**SETTINGS, "shift": False, "abs": False}
    assert levels(redline, settings=quiet) == (0, 0)


def test_engine_hum_only_when_asked_for():
    assert levels(Sample(rpm=3500, max_rpm=7000)) == (0, 0)
    hum = levels(Sample(rpm=3500, max_rpm=7000), settings={**SETTINGS, "engine": True})
    assert 0.1 < hum[0] < 0.25


def test_settings_from_the_phone_are_checked():
    out = validate_settings({"strength": 0.3, "engine": True, "unknown": 1}, SETTINGS)
    assert out["strength"] == 0.3 and out["engine"] is True and "unknown" not in out
    for bad in ({"strength": 2}, {"gears": 1}, {"strength": "x"}, []):
        with pytest.raises(ValueError):
            validate_settings(bad, SETTINGS)


def test_levels_become_serial_lines():
    assert levels_line(1.0, 0.5) == "V255,128"
    assert levels_line(-1, 3) == "V0,255"


def test_off_without_a_driving_phone_but_test_button_works():
    lines = []

    class Link:
        is_open = True
        try_open = staticmethod(lambda now: True)
        send_line = staticmethod(lambda line, now: lines.append(line) or True)

    vib = Vibration({**SETTINGS}, link=Link())
    vib.rumble = (1.0, 1.0)
    vib.tick(1.0, Sample(), active=True)
    vib.tick(1.01, Sample(), active=False)  # phone gone / watchdog released the controls
    assert lines == ["V255,255", "V0,0"]
    vib.test(2.0)
    vib.tick(2.05, Sample(), active=False)  # left first...
    vib.tick(2.3, Sample(), active=False)   # ...then right
    assert lines[-2:] == ["V255,0", "V0,255"]
