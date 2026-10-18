// PocketWheel force feedback base: force from the PC over USB -> RC ESC pulse -> motor.
//
// The PC (python main.py, with "ffb" enabled) sends one line about 100 times a second:
//   F<-1000..1000>   force: negative turns the wheel left, positive right, 0 = none
//   ?                who are you? (answered with VERSION)
// Each force becomes a servo-style pulse for the ESC, like an RC car:
//   1500 us = stop, towards 1000 us = full one way, towards 2000 us = full the other way.
//
// Wiring (Arduino Uno / Nano / Pro Micro):
//   ESC signal (white or yellow) -> pin 9
//   ESC ground (black or brown)  -> GND      (the grounds must be connected)
//   ESC red wire (BEC 5-6 V)     -> leave it unconnected while the Arduino is on USB
//   ESC power leads -> the battery;  ESC motor leads -> the motor
//
// ESC setup: it has to go both ways straight away. Car ESCs normally brake first and only
// reverse after a second "double tap" - that ruins force feedback. Set the ESC to
// forward/reverse without brake ("Fwd/Rev", crawler mode). A brushed motor works much better
// than a sensorless brushless one: force feedback is mostly pushing while barely moving.
//
// Gearing: a 1:4 reduction gives about 4x the motor's torque at the wheel. Strength is set
// by MAX_US_OFFSET below and by the phone's Force feedback strength slider.
//
// The vibration motors use their own Arduino (arduino/pocketwheel_vibration); PocketWheel tells
// the two boards apart by what they answer to "?".
//
// FIRST RUN: set DEADBAND_US for your ESC first (arduino/motor_spin_test finds it), keep the
// phone's Strength slider low (~20%) and your hands clear. Tilt the phone off center:
// the motor should push it back towards center. If it pushes away instead (and runs off),
// set INVERT to true (or tick "Invert direction" on the phone, or swap the motor wires).

#include <Servo.h>

const uint8_t ESC_PIN = 9;
const int CENTER_US = 1500;
const int MAX_US_OFFSET = 500;   // full force = 1500 +/- this (1000..2000). Max 500.
const int DEADBAND_US = 290;     // ESCs ignore pulses this close to 1500; jump past it so
                                 // small forces still move the motor. Set it ~10 below where
                                 // motor_spin_test first turned the motor (here 1800 / 1200,
                                 // i.e. 300 from stop both ways).
const bool INVERT = false;       // motor pushes the wrong way? flip this
const unsigned long TIMEOUT_MS = 200;  // no data for this long (PC or phone gone) -> stop
const unsigned long ARM_MS = 3000;     // hold 1500 after power-up so the ESC arms
const float SLEW_PER_MS = 0.02;        // max force change per ms (full force in 50 ms):
                                       // softens jolts without crawling through the dead band
const char VERSION[] = "POCKETWHEEL FFB 1";

Servo esc;
char line[16];
uint8_t len = 0;
int force = 0;                 // -1000..1000, latest from the PC
unsigned long lastData = 0;    // millis() of the latest force
unsigned long lastStep = 0;
float smoothed = 0;            // force actually applied, -1000..1000, eased towards `force`

void setup() {
  Serial.begin(115200);
  esc.attach(ESC_PIN, 1000, 2000);
  esc.writeMicroseconds(CENTER_US);
  pinMode(LED_BUILTIN, OUTPUT);
}

// -1000..1000 -> pulse in microseconds, skipping the ESC's dead band around center.
int toPulse(int f) {
  if (INVERT) f = -f;
  if (abs(f) < 5) return CENTER_US;
  long offset = DEADBAND_US + (long)(MAX_US_OFFSET - DEADBAND_US) * abs(f) / 1000;
  return f > 0 ? CENTER_US + offset : CENTER_US - offset;
}

void handleLine(const char *text) {
  if (text[0] == 'F') {
    force = constrain(atol(text + 1), -1000L, 1000L);
    lastData = millis();
  } else if (text[0] == '?') {
    Serial.println(VERSION);
  }
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      line[len] = '\0';
      if (len > 0) handleLine(line);
      len = 0;
    } else if (len < sizeof(line) - 1) {
      line[len++] = c;
    } else {
      len = 0;  // too long: garbage, start over
    }
  }
}

void loop() {
  readSerial();
  unsigned long now = millis();

  bool fresh = lastData != 0 && now - lastData < TIMEOUT_MS;
  int target = (now >= ARM_MS && fresh) ? force : 0;

  // Ease the FORCE (not the pulse) at most SLEW_PER_MS, then map it past the dead band, so a
  // push starts at once instead of crawling through the ESC's dead zone. Timeout = instant stop.
  float step = SLEW_PER_MS * 1000.0 * (now - lastStep);
  lastStep = now;
  if (!fresh) {
    smoothed = 0;
  } else {
    smoothed += constrain(target - smoothed, -step, step);
  }

  int pulse = toPulse((int)smoothed);
  esc.writeMicroseconds(pulse);
  digitalWrite(LED_BUILTIN, pulse != CENTER_US ? HIGH : LOW);
}
