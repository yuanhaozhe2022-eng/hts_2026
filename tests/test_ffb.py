import pytest

from server.ffb import FfbModel, ForceFeedback, force_line, validate_settings
from server.telemetry import Sample

SETTINGS = {"enabled": True, "invert": False, "strength": 1.0, "spring": 1.0, "damping": 0.0,
            "road": 0.0}


def force(settings=SETTINGS, sample=None, steer=0.0, rumble=0.0, now=10.0, dt=0.01, model=None):
    return (model or FfbModel()).force(settings, sample or Sample(speed_kmh=0), steer, rumble, now, dt)


def test_spring_pushes_back_to_center_and_firms_up_with_speed():
    parked = force(steer=0.5, sample=Sample(speed_kmh=0))
    fast = force(steer=0.5, sample=Sample(speed_kmh=120))
    assert parked < 0 and fast < parked          # turned right -> pushed left, harder when fast
    assert force(steer=-0.5, sample=Sample(speed_kmh=120)) == pytest.approx(-fast)
    assert force(steer=0.0) == 0


def test_game_force_feedback_wins_when_the_game_provides_it():
    assert force(sample=Sample(speed_kmh=100, ffb=0.4), steer=0.9) == pytest.approx(0.4)
    assert force(sample=Sample(speed_kmh=100, ffb=3.0)) == 1.0  # clamped


def test_game_force_can_be_turned_down_to_just_the_centering_spring():
    sample = Sample(speed_kmh=100, ffb=0.4)    # game pulls right, wheel turned right
    spring_only = force(sample=Sample(speed_kmh=100), steer=0.3)
    assert force({**SETTINGS, "game": 0.0}, sample=sample, steer=0.3) == pytest.approx(spring_only)
    half = force({**SETTINGS, "game": 0.5}, sample=sample, steer=0.3)
    assert half == pytest.approx(0.5 * 0.4 + 0.5 * spring_only)


def test_invert_strength_damping_and_road_feel():
    assert force({**SETTINGS, "invert": True}, steer=0.5) == pytest.approx(-force(steer=0.5))
    assert force({**SETTINGS, "strength": 0.5}, steer=0.5) == pytest.approx(force(steer=0.5) / 2)
    model = FfbModel()
    damped = {**SETTINGS, "spring": 0.0, "damping": 1.0}
    model.force(damped, Sample(), 0.0, 0.0, 10.0, 0.01)
    for i in range(10):  # wheel turning right quickly -> damping pushes left
        f = model.force(damped, Sample(), 0.05 * (i + 1), 0.0, 10.01 + i * 0.01, 0.01)
    assert f < 0
    shaky = {**SETTINGS, "spring": 0.0, "road": 1.0}
    shakes = {force(shaky, rumble=1.0, now=10 + i / 100) for i in range(10)}
    assert min(shakes) < 0 < max(shakes)


def test_boost_over_100_percent_and_minimum_force():
    gentle = force(steer=0.05, sample=Sample(speed_kmh=60))  # a small pull, about -0.15
    assert -0.3 < gentle < 0
    assert force({**SETTINGS, "strength": 2.0}, steer=0.05, sample=Sample(speed_kmh=60)) == \
        pytest.approx(2 * gentle)
    assert force({**SETTINGS, "strength": 2.0}, steer=0.9, sample=Sample(speed_kmh=60)) == -1.0
    lifted = force({**SETTINGS, "minimum": 0.4}, steer=0.05, sample=Sample(speed_kmh=60))
    assert lifted == pytest.approx(-(0.4 + 0.6 * abs(gentle)))
    assert force({**SETTINGS, "minimum": 0.4}, steer=0.0) == 0  # nothing stays nothing


def test_damping_is_steady_when_steering_updates_arrive_unevenly():
    # The phone's angle changes ~60 times a second while the loop ticks at 100 Hz, so some
    # ticks see no change. Damping must not flick between 0 and a spike.
    damped = {**SETTINGS, "spring": 0.0, "damping": 1.0}
    model, now, steer, out = FfbModel(), 10.0, 0.0, []
    for tick in range(100):
        now += 0.01
        if tick % 5 in (0, 2, 3):          # 3 updates per 5 ticks = 60 Hz, uneven
            steer += 0.01                  # turning right steadily (0.6 full-lock/s)
        out.append(model.force(damped, Sample(), steer, 0.0, now, 0.01))
    late = out[40:]
    assert all(f < 0 for f in late)        # always resisting, never flipping sign
    assert max(late) - min(late) < 0.03    # and steady


def test_minimum_force_never_lifts_damping_jitter():
    model = FfbModel()
    s = {**SETTINGS, "spring": 0.0, "damping": 1.0, "minimum": 0.4}
    model.force(s, Sample(), 0.0, 0.0, 10.0, 0.01)
    f = model.force(s, Sample(), 0.002, 0.0, 10.016, 0.016)  # a tiny wobble
    assert abs(f) < 0.1


def test_settings_from_the_phone_are_checked():
    out = validate_settings({"strength": 0.8, "invert": True, "unknown": 1}, SETTINGS)
    assert out["strength"] == 0.8 and out["invert"] is True and "unknown" not in out
    for bad in ({"strength": 2.5}, {"minimum": 0.9}, {"enabled": 1}, {"damping": "x"}, []):
        with pytest.raises(ValueError):
            validate_settings(bad, SETTINGS)


def test_force_lines_and_no_force_without_a_driving_phone():
    assert force_line(0.5) == "F500" and force_line(-1.7) == "F-1000"
    lines = []

    class Link:
        is_open = True
        try_open = staticmethod(lambda now: True)
        send_line = staticmethod(lambda line, now: lines.append(line) or True)

    ffb = ForceFeedback(dict(SETTINGS), link=Link())
    ffb.tick(1.0, Sample(speed_kmh=100), 0.8, active=True)
    ffb.tick(1.01, Sample(speed_kmh=100), 0.8, active=False)  # watchdog released the controls
    assert lines[0].startswith("F-") and lines[1] == "F0"
