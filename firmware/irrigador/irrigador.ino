#include <LiquidCrystal.h>
#include <string.h>

LiquidCrystal lcd(12, 11, 5, 4, 3, 2);

const byte PUMP = 7;
const byte GREEN = 8;
const byte RED = 9;
const byte YELLOW = 10;
const int SOIL_DRY = 0;    // Referência do Tinkercad, recalibrar no sensor físico
const int SOIL_WET = 876;  // Referência do Tinkercad, recalibrar no sensor físico
const int DRY_THRESHOLD = 40;
const unsigned long WATER_MS = 3000;
const unsigned long REST_MS = 5000;

bool automatic = true;
bool dryCycle = false;
bool pumpOn = false;
unsigned long phaseStart = 0;
unsigned long lastReport = 0;
char command[12];
byte commandLength = 0;
bool commandOverflow = false;

void readCommands() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      command[commandLength] = '\0';
      if (!commandOverflow) {
        if (strcmp(command, "PAUSE") == 0) automatic = false;
        if (strcmp(command, "AUTO") == 0) automatic = true;
      }
      commandLength = 0;
      commandOverflow = false;
    } else if (c != '\r') {
      if (commandLength < sizeof(command) - 1) command[commandLength++] = c;
      else commandOverflow = true;
    }
  }
}

void setup() {
  digitalWrite(PUMP, LOW);
  pinMode(PUMP, OUTPUT);
  pinMode(RED, OUTPUT);
  pinMode(YELLOW, OUTPUT);
  pinMode(GREEN, OUTPUT);
  lcd.begin(16, 2);
  Serial.begin(9600);
}

void loop() {
  readCommands();
  int soil = constrain(map(analogRead(A0), SOIL_DRY, SOIL_WET, 0, 100), 0, 100);
  int light = map(analogRead(A1), 0, 1023, 0, 100);
  unsigned long now = millis();
  bool wasOn = pumpOn;
  bool dry = soil < DRY_THRESHOLD;
  if (!automatic || !dry) {
    dryCycle = false;
    pumpOn = false;
  } else if (!dryCycle) {
    dryCycle = true;
    phaseStart = now;
    pumpOn = true;
  } else if (now - phaseStart >= (pumpOn ? WATER_MS : REST_MS)) {
    phaseStart = now;
    pumpOn = !pumpOn;
  }

  digitalWrite(PUMP, pumpOn);
  digitalWrite(RED, dry);
  digitalWrite(YELLOW, pumpOn);
  digitalWrite(GREEN, !dry);

  if (wasOn != pumpOn || now - lastReport >= 1000) {
    lastReport = now;
    lcd.setCursor(0, 0);
    lcd.print(F("Umidade: "));
    if (soil < 100) lcd.print(' ');
    if (soil < 10) lcd.print(' ');
    lcd.print(soil);
    lcd.print(F("%   "));
    lcd.setCursor(0, 1);
    lcd.print(pumpOn ? F("Motor: LIGADO   ") : F("Motor: DESLIGADO"));
    Serial.print(F("DATA,"));
    Serial.print(soil);
    Serial.print(',');
    Serial.print(light);
    Serial.print(',');
    Serial.print(pumpOn ? 1 : 0);
    Serial.print(',');
    Serial.println(automatic ? F("AUTO") : F("PAUSE"));
  }
}
