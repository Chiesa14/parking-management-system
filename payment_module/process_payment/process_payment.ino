#include <SPI.h>
#include <MFRC522.h>

#define RST_PIN 9
#define SS_PIN 10

MFRC522 rfid(SS_PIN, RST_PIN);
MFRC522::Uid savedUid;

void setup() {
  Serial.begin(9600);
  SPI.begin();
  rfid.PCD_Init();
  Serial.println("Place your RFID card...");
}

void loop() {
  // Wait for card
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) {
    return;
  }

  savedUid = rfid.uid;  // Store UID for future authentication

  // Read plate number from Block 2
  byte block2[18];
  if (!readBlock(2, block2)) {
    Serial.println("Failed to read block 2");
    haltAndStop();
    return;
  }

  // Read balance from Block 4
  byte block4[18];
  if (!readBlock(4, block4)) {
    Serial.println("Failed to read block 4");
    haltAndStop();
    return;
  }

  // Convert byte arrays to strings
  String plate = bytesToString(block2);
  String balance = bytesToString(block4);

  // Send to serial
  Serial.print("PLATE:");
  Serial.print(plate);
  Serial.print("|BALANCE:");
  Serial.println(balance);

  haltAndStop(); // End session
  delay(2000);   // Wait before next scan
}

// Authenticate and read from a block
bool readBlock(byte blockNum, byte* buffer) {
  MFRC522::MIFARE_Key key;
  for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF;  // Default key A

  MFRC522::StatusCode status;

  // Authenticate
  status = rfid.PCD_Authenticate(
    MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNum, &key, &savedUid
  );
  if (status != MFRC522::STATUS_OK) {
    Serial.print("Auth failed for block "); Serial.println(blockNum);
    return false;
  }

  byte size = 18;
  status = rfid.MIFARE_Read(blockNum, buffer, &size);
  if (status != MFRC522::STATUS_OK) {
    Serial.print("Read failed for block "); Serial.println(blockNum);
    return false;
  }

  return true;
}

// Convert block data to string
String bytesToString(byte* buffer) {
  String result = "";
  for (int i = 0; i < 16; i++) {
    if (buffer[i] == 0) break;
    result += (char)buffer[i];
  }
  return result;
}

// Cleanup function to halt card and stop encryption
void haltAndStop() {
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}
