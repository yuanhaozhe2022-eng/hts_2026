// PocketWheel vibration motors: rumble from the PC over USB -> two small motors in the mount.
//
// The PC (python main.py, with "vibration" turned on) sends one line about 100 times a second:
//   V<left 0..255>,<right 0..255>   how hard each motor should buzz
//   ?                                who are you? (answered with VERSION)
// Like an Xbox controller: left and right motor. One motor? Wire only the left one.
//
// WIRING, small vibration motors (coin / ERM "pager" motors, 3-5 V) - the usual way:
//   Arduino pin 5 (left) / pin 6 (right) -> 220 ohm -> gate of a logic-level N-MOSFET
//     (AO3400, IRLZ44N, ...) or base of an NPN transistor (2N2222 / S8050, 1 k resistor).
//   10 k from gate to GND (keeps the motor off while the Arduino boots).
//   Motor + -> 5 V (Arduino 5V for small motors up to ~100 mA each; bigger ones: a battery)
//   Motor - -> MOSFET drain (or transistor collector); source/emitter -> GND.
//   A diode across each motor (1N4148 / 1N5819, stripe to +) to absorb its voltage spikes.
//   All grounds connected. Never power a motor straight from an Arduino pin.
//
// WIRING, reusing the RC ESC + battery with a small motor with an off-centre weight:
//   set OUTPUT_MODE to ESC_MODE: pin 5 sends servo pulses, 1500 us = off, up to 2000 us = full
//   (forward only, so no brake/reverse trouble). ESC signal -> pin 5, ESC ground -> GND.

#include <Servo.h>

enum Mode { MOSFET_MODE, ESC_MODE };
const Mode OUTPUT_MODE = MOSFET_MODE;

const uint8_t MOTOR_PINS[2] = {5, 6};  // left, right (PWM pins)
const uint8_t MIN_DUTY = 60;      // a small motor stalls below this; any buzz starts here
const unsigned long KICK_MS = 20; // full power this long to get a stopped motor spinning
const int ESC_MAX_US = 2000;      // ESC_MODE: pulse at full strength (1500 = off)
const unsigned long TIMEOUT_MS = 200;  // no data for this long (PC or phone gone) -> off
const char VERSION[] = "POCKETWHEEL VIBRATION 1";

Servo esc;
char line[24];
uint8_t len = 0;
uint8_t level[2] = {0, 0};          // latest from the PC
unsigned long lastData = 0;
unsigned long startedAt[2] = {0, 0}; // when each motor last started from stopped
bool running[2] = {false, false};

void setup() {
  Serial.begin(115200);
  if (OUTPUT_MODE == ESC_MODE) {
    esc.attach(MOTOR_PINS[0], 1000, 2000);
    esc.writeMicroseconds(1500);  // also arms the ESC
  } else {
    for (uint8_t i = 0; i < 2; i++) {
      pinMode(MOTOR_PINS[i], OUTPUT);
      analogWrite(MOTOR_PINS[i], 0);
    }
  }
  pinMode(LED_BUILTIN, OUTPUT);
}

void handleLine(char *text) {
  if (text[0] == 'V') {
    char *comma = strchr(text, ',');
    long left = atol(text + 1);
    long right = comma ? atol(comma + 1) : left;
    level[0] = constrain(left, 0L, 255L);
    level[1] = constrain(right, 0L, 255L);
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

// 0..255 request -> PWM duty, with the stall floor and a kick to start.
uint8_t duty(uint8_t i, uint8_t want, unsigned long now) {
  if (want == 0) {
    running[i] = false;
    return 0;
  }
  if (!running[i]) {
    running[i] = true;
    startedAt[i] = now;
  }
  if (now - startedAt[i] < KICK_MS) return 255;
  return map(want, 1, 255, MIN_DUTY, 255);
}

void loop() {
  readSerial();
  unsigned long now = millis();
  bool fresh = lastData != 0 && now - lastData < TIMEOUT_MS;
  uint8_t want[2] = {fresh ? level[0] : (uint8_t)0, fresh ? level[1] : (uint8_t)0};

  if (OUTPUT_MODE == ESC_MODE) {
    uint8_t strongest = max(want[0], want[1]);
    esc.writeMicroseconds(strongest ? map(strongest, 1, 255, 1550, ESC_MAX_US) : 1500);
  } else {
    for (uint8_t i = 0; i < 2; i++) analogWrite(MOTOR_PINS[i], duty(i, want[i], now));
  }
  digitalWrite(LED_BUILTIN, (want[0] || want[1]) ? HIGH : LOW);
}
