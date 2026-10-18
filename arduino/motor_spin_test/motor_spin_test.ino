// Find the ESC's starting point: ramps slowly from stop towards full, printing each pulse.
// Watch the motor; the number on screen when it STARTS turning is your minimum.
//
// Open Tools > Serial Monitor at 115200 baud. Type s + Enter any time to stop for good.
// Ramps 1500 -> 2000 (one way), back to stop, then 1500 -> 1000 (the other way).
// Motor NOT geared to the phone mount, hands clear.
//
// ESC signal -> pin 9, ESC ground -> GND, ESC red wire not connected.
// Then in pocketwheel_ffb.ino: DEADBAND_US = (start pulse - 1500) - 10, for the bigger of the
// two directions, and MAX_US_OFFSET a good way above it (up to 500).

#include <Servo.h>

const int STEP_US = 10;            // how much each step adds
const unsigned long STEP_MS = 400; // how long each step lasts (time to see the motor react)

Servo esc;
bool stopped = false;

// Hold a pulse for ms, printing it; returns false if "s" was typed.
bool hold(int us, unsigned long ms) {
  esc.writeMicroseconds(us);
  unsigned long start = millis();
  while (millis() - start < ms) {
    while (Serial.available()) {
      char c = Serial.read();
      if (c == 's' || c == 'S') stopped = true;
    }
    if (stopped) {
      esc.writeMicroseconds(1500);
      return false;
    }
    delay(5);
  }
  return true;
}

void ramp(int to, const char *name) {
  int dir = to > 1500 ? 1 : -1;
  Serial.print("Ramping ");
  Serial.println(name);
  for (int us = 1500; dir * (to - us) >= 0; us += dir * STEP_US) {
    Serial.print("  ");
    Serial.print(us);
    Serial.print(" us   (");
    Serial.print(dir * (us - 1500));
    Serial.println(" from stop)");
    if (!hold(us, STEP_MS)) return;
  }
  hold(1500, 2000);  // stop between directions
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  esc.attach(9, 1000, 2000);
  esc.writeMicroseconds(1500);
  Serial.println();
  Serial.println("Stop for 3 s so the ESC arms (connect the battery now)...");
  hold(1500, 3000);
  digitalWrite(LED_BUILTIN, HIGH);
  if (!stopped) ramp(2000, "one way (1500 -> 2000)");
  if (!stopped) ramp(1000, "the other way (1500 -> 1000)");
  esc.writeMicroseconds(1500);
  digitalWrite(LED_BUILTIN, LOW);
  Serial.println(stopped ? "Stopped by you." : "Done. Stopped.");
}

void loop() {
  esc.writeMicroseconds(1500);
  delay(20);
}
