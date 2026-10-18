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
// FIRST RUN: keep MAX_US_OFFSET low (150) and your hands clear. Tilt the phone off center:
// the motor should push it back towards center. If it pushes away instead (and runs off),
// set INVERT to true (or tick "Invert direction" on the phone, or swap the motor wires).

#include <Servo.h>

const uint8_t ESC_PIN = 9;
const int CENTER_US = 1500;
const int MAX_US_OFFSET = 300;   // full force = 1500 +/- this. 500 uses the whole 1000..2000.
const int DEADBAND_US = 40;      // ESCs ignore pulses this close to 1500; jump past it so
                                 // small forces still move the motor. Tune for your ESC.
const bool INVERT = false;       // motor pushes the wrong way? flip this
const unsigned long TIMEOUT_MS = 200;  // no data for this long (PC or phone gone) -> stop
const unsigned long ARM_MS = 3000;     // hold 1500 after power-up so the ESC arms
const float SLEW_US_PER_MS = 4.0;      // max pulse change per ms: softens jolts
const char VERSION[] = "POCKETWHEEL FFB 1";

Servo esc;
char line[16];
uint8_t len = 0;
int force = 0;                 // -1000..1000, latest from the PC
unsigned long lastData = 0;    // millis() of the latest force
unsigned long lastStep = 0;
float pulse = CENTER_US;       // what goes to the ESC right now

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

  int target = CENTER_US;
  bool fresh = lastData != 0 && now - lastData < TIMEOUT_MS;
  if (now >= ARM_MS && fresh) target = toPulse(force);

  // Move towards the target at most SLEW_US_PER_MS. Stopping (timeout) is immediate.
  float step = SLEW_US_PER_MS * (now - lastStep);
  lastStep = now;
  if (target == CENTER_US && !fresh) {
    pulse = CENTER_US;
  } else {
    pulse += constrain(target - pulse, -step, step);
  }

  esc.writeMicroseconds((int)pulse);
  digitalWrite(LED_BUILTIN, abs((int)pulse - CENTER_US) > DEADBAND_US ? HIGH : LOW);
}
