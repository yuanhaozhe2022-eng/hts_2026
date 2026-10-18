// PocketWheel force feedback: MOTOR TEST. No PC software needed.
//
// Open Tools > Serial Monitor at 115200 baud (any line ending). Connect / switch on the ESC
// battery and wait for its startup beeps to finish. Then type a command and press Enter:
//
//   1700     hold that pulse (1000..2000 us) for HOLD_MS, then back to 1500 (stop) by itself
//            -> try 1600, 1700, 1800, 1900, 2000, then 1400, 1300, 1200, 1100, 1000
//   g        both ways: LEFT then RIGHT at each step, 300 ... 500 us from center
//            (ends at full: 1000 and 2000)
//   o        one way: RIGHT only at each step, 1800 ... 2000
//   s        stop now (1500)
//
// The LED is on while a pulse other than 1500 is being sent.
//
// Use it to find:
//   - the dead band: the smallest offset from 1500 that turns the motor
//     -> in pocketwheel_ffb.ino set DEADBAND_US about 10 below it, MAX_US_OFFSET above it
//   - whether BOTH directions work (only one = the ESC is in a brake mode, not Fwd/Rev)
//
// Same wiring as pocketwheel_ffb: ESC signal -> pin 9, ESC ground -> GND, ESC red wire not
// connected, battery -> ESC, motor -> ESC motor wires. A 555 motor needs a BRUSHED ESC
// (2 motor wires). Run it with the motor NOT geared to the phone mount first, hands clear.

#include <Servo.h>

const uint8_t ESC_PIN = 9;
const int CENTER_US = 1500;
// For "g" / "o": offsets from 1500. This ESC starts moving at 300 from stop (1800 / 1200),
// so test from there to full (500 = 2000 one way, 1000 the other).
const int STEPS_US[] = {300, 350, 400, 450, 500};
const unsigned long HOLD_MS = 2000;  // a typed pulse lasts this long, then stop
const unsigned long PUSH_MS = 500;   // each "g" step
const unsigned long GAP_MS = 700;

Servo esc;
char input[12];
uint8_t len = 0;

void send(int us) {
  esc.writeMicroseconds(us);
  digitalWrite(LED_BUILTIN, us != CENTER_US ? HIGH : LOW);
}

// Reads a line if one is complete. Returns true and fills `input` when Enter was pressed.
bool readLine() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (len == 0) continue;
      input[len] = '\0';
      len = 0;
      return true;
    }
    if (len < sizeof(input) - 1) input[len++] = c;
  }
  return false;
}

// Holds a pulse for ms; returns false early (and stops) if "s" arrives.
bool hold(int us, unsigned long ms) {
  send(us);
  unsigned long start = millis();
  while (millis() - start < ms) {
    if (readLine() && (input[0] == 's' || input[0] == 'S')) {
      send(CENTER_US);
      Serial.println("Stopped.");
      return false;
    }
    delay(5);
  }
  return true;
}

// bothWays: LEFT then RIGHT at each step; otherwise RIGHT only.
void stepTest(bool bothWays) {
  Serial.println(bothWays ? "Both-ways step test (type s + Enter to stop):"
                          : "One-way step test (type s + Enter to stop):");
  for (int us : STEPS_US) {
    Serial.print("  ");
    Serial.print(us);
    Serial.print(" us:");
    if (bothWays) {
      Serial.print("  LEFT ");
      Serial.print(CENTER_US - us);
      if (!hold(CENTER_US - us, PUSH_MS) || !hold(CENTER_US, GAP_MS)) return;
    }
    Serial.print("   RIGHT ");
    Serial.println(CENTER_US + us);
    if (!hold(CENTER_US + us, PUSH_MS) || !hold(CENTER_US, GAP_MS * 2)) return;
  }
  send(CENTER_US);
  Serial.println("Step test done.");
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  esc.attach(ESC_PIN, 1000, 2000);
  send(CENTER_US);
  Serial.println();
  Serial.println("PocketWheel motor test. Sending 1500 us (stop) on pin 9.");
  Serial.println("Wait for the ESC's beeps to finish, then type a pulse like 1900, or g, o, s.");
}

void loop() {
  send(CENTER_US);
  if (!readLine()) {
    delay(5);
    return;
  }
  if (input[0] == 'g' || input[0] == 'G') {
    stepTest(true);
  } else if (input[0] == 'o' || input[0] == 'O') {
    stepTest(false);
  } else if (input[0] == 's' || input[0] == 'S') {
    Serial.println("Stopped.");
  } else {
    long us = atol(input);
    if (us < 1000 || us > 2000) {
      Serial.println("Type a pulse from 1000 to 2000, or g, o, s.");
      return;
    }
    Serial.print("Holding ");
    Serial.print(us);
    Serial.print(" us for ");
    Serial.print(HOLD_MS / 1000.0, 1);
    Serial.println(" s...");
    if (hold((int)us, HOLD_MS)) Serial.println("Back to 1500 (stop).");
  }
  send(CENTER_US);
}
