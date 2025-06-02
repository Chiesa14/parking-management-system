#include <SPI.h>
#include <MFRC522.h>

#define SS_PIN 10
#define RST_PIN 9

MFRC522 rfid(SS_PIN, RST_PIN);
MFRC522::Uid savedUid;

String plate, balanceStr;
long currentBalance = 0;

void setup() {
  Serial.begin(115200);
  SPI.begin();
  rfid.PCD_Init();
  Serial.println("🔄 Arduino ready and waiting for RFID...");
}

void loop() {
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) {
    return;
  }

  savedUid = rfid.uid;

  // Read plate number (Block 2)
  byte block2[18];
  if (!readBlock(2, block2)) {
    Serial.println("❌ Failed to read block 2");
    haltCard();
    return;
  }

  // Read balance (Block 4)
  byte block4[18];
  if (!readBlock(4, block4)) {
    Serial.println("❌ Failed to read block 4");
    haltCard();
    return;
  }

  plate = bytesToString(block2);
  balanceStr = bytesToString(block4);
  currentBalance = balanceStr.toInt();

  Serial.print("PLATE:");
  Serial.print(plate);
  Serial.print("|BALANCE:");
  Serial.println(currentBalance);

  // Wait for PAY command from PC
  String command = waitForCommand();
  if (command.startsWith("PAY:")) {
    int amount = command.substring(4).toInt();
    if (amount > 0 && currentBalance >= amount) {
      long newBalance = currentBalance - amount;

      if (writeBlock(4, String(newBalance).c_str())) {
        Serial.println("DONE");
      } else {
        Serial.println("FAIL");
      }
    } else {
      Serial.println("FAIL");
    }
  }

  haltCard();
}

String waitForCommand() {
  String input = "";
  unsigned long start = millis();
  while ((millis() - start) < 2000) {
    if (Serial.available()) {
      input = Serial.readStringUntil('\n');
      input.trim();
      break;
    }
  }
  return input;
}

bool readBlock(byte blockNum, byte* buffer) {
  MFRC522::MIFARE_Key key;
  for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF;

  MFRC522::StatusCode status = rfid.PCD_Authenticate(
    MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNum, &key, &savedUid
  );
  if (status != MFRC522::STATUS_OK) {
    Serial.print("Auth failed for block "); Serial.println(blockNum);
    return false;
  }

  byte size = 18;
  status = rfid.MIFARE_Read(blockNum, buffer, &size);
  return status == MFRC522::STATUS_OK;
}

bool writeBlock(byte blockNum, const char* data) {
  MFRC522::MIFARE_Key key;
  for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF;

  MFRC522::StatusCode status = rfid.PCD_Authenticate(
    MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNum, &key, &savedUid
  );
  if (status != MFRC522::STATUS_OK) {
    Serial.print("Auth failed for block "); Serial.println(blockNum);
    return false;
  }

  byte buffer[16];
  memset(buffer, 0, 16);
  strncpy((char*)buffer, data, 16);

  status = rfid.MIFARE_Write(blockNum, buffer, 16);
  return status == MFRC522::STATUS_OK;
}

String bytesToString(byte* buffer) {
  String result = "";
  for (int i = 0; i < 16; i++) {
    if (buffer[i] == 0) break;
    result += (char)buffer[i];
  }
  return result;
}

void haltCard() {
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}