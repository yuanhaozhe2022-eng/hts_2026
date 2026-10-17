import ctypes
import struct

import pytest

from server.state import BTN_SHIFT_DOWN, BTN_SHIFT_UP, InputState
from server.telemetry import Sample
from server.telemetry.assetto import AC_LIVE, AssettoSource, Graphics, Physics, Static
from server.telemetry.beamng import (DASH_LIGHTS, DEFAULT_MAX_RPM, OG_TURBO, OUTGAUGE, BeamNGSource,
                                     parse_outgauge)
from server.telemetry.hub import TelemetryHub


def outgauge(gear=3, rpm=3500.0, speed_ms=20.0, show_lights=0, car=b"pick", with_id=False,
             flags=0, turbo=0.0, eng_temp=90.0, fuel=0.5, dash_lights=1):
    data = OUTGAUGE.pack(1234, car, flags, gear, 0, speed_ms, rpm, turbo, eng_temp, fuel, 0, 90,
                         dash_lights, show_lights, 0.5, 0, 0, b"", b"")
    return data + struct.pack("<i", 7) if with_id else data


def test_outgauge_size_matches_spec():
    assert OUTGAUGE.size == 92


def test_parse_outgauge_fields():
    p = parse_outgauge(outgauge(gear=4, rpm=5123.5, speed_ms=10, show_lights=1, fuel=0.25,
                                eng_temp=95.5, turbo=1.25, flags=OG_TURBO))
    assert (p.car, p.gear, p.rpm, p.shift_light) == ("pick", 4, 5123.5, True)
    assert p.speed_kmh == 36.0
    assert (p.fuel, p.engine_temp, p.boost, p.turbo_gauge) == (0.25, 95.5, 1.25, True)


def test_outgauge_lights_only_lists_what_the_car_has():
    has = DASH_LIGHTS["abs"] | DASH_LIGHTS["handbrake"] | DASH_LIGHTS["signal_l"]
    on = DASH_LIGHTS["handbrake"] | DASH_LIGHTS["tc"]  # tc "on" but the car has no TC light
    assert parse_outgauge(outgauge(dash_lights=has, show_lights=on)).lights == {
        "abs": False, "handbrake": True, "signal_l": False}


def test_beamng_sample_extras():
    src = BeamNGSource()
    src.handle_packet(outgauge(fuel=0.4, eng_temp=88, turbo=0.0), now=1.0)
    assert src.latest.fuel == pytest.approx(0.4) and (src.latest.engine_temp, src.latest.boost) == (88, None)
    src.handle_packet(outgauge(turbo=0.8), now=1.1)   # car proves it has a turbo...
    src.handle_packet(outgauge(turbo=0.0), now=1.2)   # ...so boost keeps showing at 0
    assert src.latest.boost == 0.0
    msg = src.latest.to_message()
    assert msg["f"] == 0.5 and msg["et"] == 90 and msg["lp"] is None


def test_parse_outgauge_accepts_optional_id_and_rejects_garbage():
    assert parse_outgauge(outgauge(with_id=True)) is not None
    assert parse_outgauge(b"\x00" * 50) is None


def test_beamng_learns_redline_and_resets_on_car_change():
    src = BeamNGSource()
    src.handle_packet(outgauge(rpm=2000), now=1.0)
    assert src.latest.max_rpm == DEFAULT_MAX_RPM
    src.handle_packet(outgauge(rpm=6500), now=1.1)
    src.handle_packet(outgauge(rpm=3000), now=1.2)
    assert src.latest.max_rpm == 6500
    assert src.latest.source == "beamng" and src.latest.time == 1.2
    src.handle_packet(outgauge(rpm=3000, car=b"bus\0"), now=1.3)
    assert src.latest.max_rpm == DEFAULT_MAX_RPM


def test_assetto_struct_layout_matches_shared_memory():
    assert Physics.gear.offset == 16
    assert Physics.rpms.offset == 20
    assert Physics.speedKmh.offset == 28
    assert Physics.pitLimiterOn.offset == 248
    assert Physics.turboBoost.offset == 276
    assert Static.maxRpm.offset == 412
    assert Static.maxFuel.offset == 416
    assert Graphics.completedLaps.offset == 132
    assert Graphics.iBestTime.offset == 148


def test_assetto_only_fresh_while_packet_id_changes():
    pages = {"physics": Physics(packetId=1, gear=3, rpms=4000, speedKmh=88.0), "static": Static(maxRpm=7500)}
    src = AssettoSource(read_pages=lambda: (pages["physics"], pages["static"], None))
    src.poll(now=10.0)
    assert (src.latest.gear, src.latest.rpm, src.latest.max_rpm, src.latest.time) == (3, 4000, 7500, 10.0)
    src.poll(now=10.5)  # same packetId: frozen data, not refreshed
    assert src.latest.time == 10.0
    pages["physics"] = Physics(packetId=2, gear=4, rpms=3000)
    src.poll(now=11.0)
    assert (src.latest.gear, src.latest.time) == (4, 11.0)


def test_assetto_fuel_pit_limiter_and_laps():
    physics = Physics(packetId=5, fuel=30.0, pitLimiterOn=1, turboBoost=0.0)
    static = Static(maxRpm=8000, maxFuel=120.0)
    graphics = Graphics(status=AC_LIVE, completedLaps=2, position=4,
                        iCurrentTime=61234, iLastTime=0, iBestTime=2147483647)
    src = AssettoSource(read_pages=lambda: (physics, static, graphics))
    src.poll(now=1.0)
    s = src.latest
    assert (s.fuel, s.boost, s.lights) == (0.25, None, {"pit": True})
    assert (s.lap.position, s.lap.lap, s.lap.current_ms, s.lap.last_ms, s.lap.best_ms) == (4, 3, 61234, None, None)
    assert s.to_message()["lp"] == {"p": 4, "n": 3, "c": 61234, "l": None, "b": None}


def test_assetto_no_lap_info_outside_a_live_session():
    src = AssettoSource(read_pages=lambda: (Physics(packetId=1), Static(), Graphics(status=1)))
    src.poll(now=1.0)
    assert src.latest.lap is None and src.latest.fuel is None


class FakeSource:
    def __init__(self, sample=None):
        self.latest = sample


def test_hub_prefers_freshest_source_and_falls_back_to_estimate():
    old = FakeSource(Sample(gear=3, source="assetto", time=9.5))
    new = FakeSource(Sample(gear=5, source="beamng", time=9.9))
    hub = TelemetryHub([old, new])
    assert hub.latest(now=10.0).source == "beamng"
    est = hub.latest(now=20.0)
    assert est.source == "est"
    assert est.gear == 5  # estimator carried on from the last real gear


def test_estimator_counts_shift_presses_once_per_press():
    hub = TelemetryHub([])
    hub.on_input(InputState(buttons=BTN_SHIFT_UP))
    hub.on_input(InputState(buttons=BTN_SHIFT_UP))  # still held: no extra shift
    hub.on_input(InputState())
    hub.on_input(InputState(buttons=BTN_SHIFT_UP))
    assert hub.latest(now=0).gear == 3  # N -> 1st -> 2nd
    for _ in range(5):
        hub.on_input(InputState(buttons=BTN_SHIFT_DOWN))
        hub.on_input(InputState())
    assert hub.latest(now=0).gear == 0  # clamps at reverse
