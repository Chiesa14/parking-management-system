#include <SPI.h>
#include <MFRC522.h>

#define SS_PIN 10
#define RST_PIN 9

MFRC522 rfid(SS_PIN, RST_PIN);
MFRC522::Uid savedUid;

String plateNumber = "";
String balance = "";

void setup() {
  Serial.begin(9600);
  SPI.begin();
  rfid.PCD_Init();
  Serial.println("Place your RFID card to read...");

  // Wait for card and store UID
  while (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) {
    delay(100);
  }

  savedUid = rfid.uid;  // Save the UID for later auth use

  // Read existing data
  String currentPlate = readBlockAsString(2);
  String currentBalance = readBlockAsString(4);

  Serial.println("📄 Current RFID data:");
  Serial.print("Plate Number: "); Serial.println(currentPlate);
  Serial.print("Balance     : "); Serial.println(currentBalance);

  // Ask if update needed
  Serial.println("Do you want to update this data? (y/n)");
  while (!Serial.available());
  char decision = Serial.read();
  decision = tolower(decision);

  if (decision == 'y') {
    getUserInput();

    if (writeBlock(2, plateNumber.c_str())) {
      Serial.println("✅ Plate number updated.");
    } else {
      Serial.println("❌ Failed to write plate number.");
    }

    if (writeBlock(4, balance.c_str())) {
      Serial.println("✅ Balance updated.");
    } else {
      Serial.println("❌ Failed to write balance.");
    }

    Serial.println("🔁 Re-reading updated data...");
    Serial.print("Plate Number: "); Serial.println(readBlockAsString(2));
    Serial.print("Balance     : "); Serial.println(readBlockAsString(4));
  } else {
    Serial.println("No update performed. Exiting...");
  }

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}

void loop() {
  // Nothing here
}

void getUserInput() {
  Serial.println("Enter new plate number (max 16 chars): ");
  while (plateNumber == "") {
    if (Serial.available()) {
      plateNumber = Serial.readStringUntil('\n');
      plateNumber.trim();
    }
  }

  Serial.println("Enter new balance (max 16 chars): ");
  while (balance == "") {
    if (Serial.available()) {
      balance = Serial.readStringUntil('\n');
      balance.trim();
    }
  }

  Serial.print("New Plate   : "); Serial.println(plateNumber);
  Serial.print("New Balance : "); Serial.println(balance);
}

bool writeBlock(byte blockNum, const char* data) {
  byte buffer[16];
  memset(buffer, 0, 16);
  strncpy((char*)buffer, data, 16);

  MFRC522::MIFARE_Key key;
  for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF;

  MFRC522::StatusCode status = rfid.PCD_Authenticate(
    MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNum, &key, &savedUid
  );
  if (status != MFRC522::STATUS_OK) {
    Serial.print("Auth failed for block "); Serial.println(blockNum);
    return false;
  }

  status = rfid.MIFARE_Write(blockNum, buffer, 16);
  if (status != MFRC522::STATUS_OK) {
    Serial.print("Write failed for block "); Serial.println(blockNum);
    return false;
  }

  return true;
}

String readBlockAsString(byte blockNum) {
  byte buffer[18];
  byte size = sizeof(buffer);
  String result = "";

  MFRC522::MIFARE_Key key;
  for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF;

  MFRC522::StatusCode status = rfid.PCD_Authenticate(
    MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNum, &key, &savedUid
  );
  if (status != MFRC522::STATUS_OK) {
    Serial.print("Auth failed for block "); Serial.println(blockNum);
    return "[Auth Failed]";
  }

  status = rfid.MIFARE_Read(blockNum, buffer, &size);
  if (status != MFRC522::STATUS_OK) {
    Serial.print("Read failed for block "); Serial.println(blockNum);
    return "[Read Failed]";
  }

  for (int i = 0; i < 16; i++) {
    if (buffer[i] == 0) break;
    result += (char)buffer[i];
  }

  return result;
}
