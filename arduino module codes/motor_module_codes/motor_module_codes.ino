#include <Servo.h>

// Pin definitions
#define TRIG_PIN 2
#define ECHO_PIN 3
#define RED_LED 4
#define BLUE_LED 5
#define SERVO_PIN 6
#define GND1 7
#define GND2 8
#define BUZZER_PIN 11

Servo gateServo;

// Gate status
bool gateOpen = false;

// Gate-open buzzer beep
bool gateBeepState = false;
unsigned long lastGateBeepToggle = 0;
const unsigned long gateBeepInterval = 500; // ms

// Buzzer pattern
bool isPlayingPattern = false;
unsigned long patternLastToggle = 0;
int patternDelay = 0;
int patternRepeat = 0;
int patternStage = 0;

// Distance check
unsigned long lastDistanceCheck = 0;
const unsigned long distanceInterval = 100; // ms

void setup() {
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(RED_LED, OUTPUT);
  pinMode(BLUE_LED, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(GND1, OUTPUT);
  pinMode(GND2, OUTPUT);
  
  digitalWrite(GND1, LOW);
  digitalWrite(GND2, LOW);
  digitalWrite(RED_LED, HIGH); // red on = gate closed
  digitalWrite(BLUE_LED, LOW);
  digitalWrite(BUZZER_PIN, LOW);
  
  gateServo.attach(SERVO_PIN);
  gateServo.write(0); // closed position
  
  Serial.begin(115200);  // Higher baud rate for faster communication
  Serial.println("[ARDUINO] Exit Control System Ready");
}

void loop() {
  // --- PRIORITIZE SERIAL COMMANDS - Check multiple times per loop ---
  for(int i = 0; i < 3; i++) {  // Check serial 3 times per loop iteration
    if (Serial.available() > 0) {
      char command = Serial.read();
      
      switch (command) {
        case '1': 
          openGate(); 
          break;
        case '0': 
          closeGate(); 
          break;
        case '2':
          // Legacy support - trigger denied access buzzer
          startBuzzerPattern(150, 6); // Fast beeps for denied access
          break;
        case 'U': 
          startBuzzerPattern(300, 3); 
          break;
        case 'P': 
          startBuzzerPattern(800, 2); 
          break;
        case 'D': 
          // Denied access - immediate response
          startBuzzerPattern(100, 8); // Faster, more urgent pattern
          Serial.println("[BUZZER] Access Denied - IMMEDIATE");
          break;
        default: 
          break;
      }
    }
  }
  
  unsigned long currentMillis = millis();
  
  // --- Gate-open beep logic ---
  if (gateOpen && currentMillis - lastGateBeepToggle >= gateBeepInterval) {
    lastGateBeepToggle = currentMillis;
    gateBeepState = !gateBeepState;
    digitalWrite(BUZZER_PIN, gateBeepState ? HIGH : LOW);
  }
  
  // --- Pattern buzzer logic ---
  if (isPlayingPattern && currentMillis - patternLastToggle >= patternDelay) {
    patternLastToggle = currentMillis;
    bool buzzerOn = (patternStage % 2 == 0);
    digitalWrite(BUZZER_PIN, buzzerOn ? HIGH : LOW);
    patternStage++;
    
    if (patternStage >= patternRepeat * 2) {
      isPlayingPattern = false;
      digitalWrite(BUZZER_PIN, LOW); // ensure buzzer ends low
      Serial.println("[BUZZER] Pattern Complete");
    }
  }
  
  // --- Distance check (less frequent to prioritize serial) ---
  if (currentMillis - lastDistanceCheck >= 500) {  // Reduced frequency
    lastDistanceCheck = currentMillis;
    long distance = getDistance();
    
    if (distance > 0 && distance < 20 && !gateOpen) {
      Serial.println("[INFO] Object Approaching: " + String(distance) + " cm");
    }
  }
}

// ---------------------------------------------
// Gate control
// ---------------------------------------------
void openGate() {
  gateServo.write(90);  // Open position
  gateOpen = true;
  digitalWrite(RED_LED, LOW);
  digitalWrite(BLUE_LED, HIGH);
  Serial.println("[GATE] Opened");
}

void closeGate() {
  gateServo.write(0);   // Closed position
  gateOpen = false;
  digitalWrite(RED_LED, HIGH);
  digitalWrite(BLUE_LED, LOW);
  gateBeepState = false;
  digitalWrite(BUZZER_PIN, LOW); // stop beep if any
  Serial.println("[GATE] Closed");
}

// ---------------------------------------------
// Buzzer pattern (non-blocking)
// ---------------------------------------------
void startBuzzerPattern(int delayTime, int repeatCount) {
  isPlayingPattern = true;
  patternDelay = delayTime;
  patternRepeat = repeatCount;
  patternStage = 0;
  patternLastToggle = millis();
  Serial.println("[BUZZER] Starting Pattern - Delay: " + String(delayTime) + "ms, Repeats: " + String(repeatCount));
}

// ---------------------------------------------
// Distance sensor
// ---------------------------------------------
long getDistance() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  
  long duration = pulseIn(ECHO_PIN, HIGH, 20000); // timeout 20ms
  if (duration == 0) return -1; // timeout occurred
  
  long distance = duration * 0.034 / 2;
  return distance;
}
