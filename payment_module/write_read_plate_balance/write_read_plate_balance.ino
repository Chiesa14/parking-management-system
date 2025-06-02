#include <SPI.h>
#include <MFRC522.h>
#include <stdlib.h>  // for strtod()

#define SS_PIN 10
#define RST_PIN 9

MFRC522 rfid(SS_PIN, RST_PIN);
MFRC522::Uid savedUid;

String plateNumber = "";
String balanceToAdd = "";

void setup() {
  Serial.begin(9600);
  SPI.begin();
  rfid.PCD_Init();
  Serial.println("📟 RFID Reader Ready. Place your RFID card to read...");
  Serial.println("Enter 'q' at any time to quit.");
}

void loop() {
  // Check for quit command
  if (Serial.available()) {
    char input = Serial.read();
    if (tolower(input) == 'q') {
      Serial.println("🛑 Exiting program...");
      rfid.PICC_HaltA();
      rfid.PCD_StopCrypto1();
      while (true); // Stop execution forever
    }
    // Clear any remaining Serial buffer
    while (Serial.available()) Serial.read();
  }

  // Improved card detection logic
  if (!rfid.PICC_IsNewCardPresent()) {
    delay(50);
    return;
  }

  if (!rfid.PICC_ReadCardSerial()) {
    delay(50);
    return;
  }

  // Save UID for authentication
  savedUid = rfid.uid;

  // Read existing data from block 2 and block 4
  String currentPlate   = readBlockAsString(2);
  String currentBalance = readBlockAsString(4);

  Serial.println("\n📄 Current RFID data:");
  Serial.print("Plate Number: "); Serial.println(currentPlate);
  Serial.print("Balance     : "); Serial.println(currentBalance);

  // Ask if update is needed
  Serial.println("Do you want to update this data? (y/n)");
  char decision = '\0';
  while (!Serial.available()) {
    delay(10); // Small delay to avoid busy‐wait
  }
  decision = Serial.read();
  decision = tolower(decision);

  // Clear Serial buffer
  while (Serial.available()) Serial.read();

  if (decision == 'y') {
    getUserInput();

    // Update plate number only if provided and valid
    if (plateNumber != "" && plateNumber != "[No Change]") {
      if (writeBlock(2, plateNumber.c_str())) {
        Serial.println("✅ Plate number updated.");
      } else {
        Serial.println("❌ Failed to write plate number.");
      }
    } else {
      Serial.println("No change to plate number.");
    }

    // Update balance if valid
    if (balanceToAdd != "" && balanceToAdd != "[No Change]") {
      float newBalance;
      bool isValidBalance = isValidNumber(currentBalance);

      if (isValidBalance) {
        // Valid current balance, add to it
        float currentBalanceValue = currentBalance.toFloat();
        float amountToAdd         = balanceToAdd.toFloat();
        newBalance = currentBalanceValue + amountToAdd;
        Serial.print("[DEBUG] Valid balance (");
        Serial.print(currentBalanceValue, 2);
        Serial.print(") + amount (");
        Serial.print(amountToAdd, 2);
        Serial.print(") = ");
        Serial.println(newBalance, 2);
      } else {
        // Invalid current balance, treat provided as new balance
        newBalance = balanceToAdd.toFloat();
        Serial.print("[DEBUG] Invalid balance (");
        Serial.print(currentBalance);
        Serial.print("), setting new balance to: ");
        Serial.println(newBalance, 2);
      }

      // Format new balance as a string (max 16 chars including null terminator)
      char newBalanceStr[16];
      dtostrf(newBalance, 0, 2, newBalanceStr);  // e.g., "123.45"

      if (writeBlock(4, newBalanceStr)) {
        Serial.println("✅ Balance updated.");
      } else {
        Serial.println("❌ Failed to write balance.");
      }
    } else {
      Serial.println("No change to balance.");
    }

    // Re‐read blocks to show updates
    Serial.println("🔁 Re-reading updated data...");
    Serial.print("Plate Number: "); Serial.println(readBlockAsString(2));
    Serial.print("Balance     : "); Serial.println(readBlockAsString(4));
  } else {
    Serial.println("No update performed.");
  }

  // Reset variables for next card
  plateNumber   = "";
  balanceToAdd  = "";

  // Properly release the current card
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  // Re‐initialize RFID reader for the next card
  rfid.PCD_Init();

  Serial.println("\n🔄 Ready for next card. Place RFID card or enter 'q' to quit...");
}


// Prompt the user (via Serial) for new plate number and balance
void getUserInput() {
  plateNumber  = "";
  balanceToAdd = "";

  // Get plate number with validation
  bool validPlate = false;
  while (!validPlate) {
    Serial.println("Enter new plate number (press Enter to keep existing): ");
    while (!Serial.available()) {
      delay(10);
    }
    plateNumber = Serial.readStringUntil('\n');
    plateNumber.trim();

    // Handle empty input (keep existing)
    if (plateNumber == "") {
      plateNumber = "[No Change]";
      validPlate = true;
    }
    // Otherwise validate content
    else if (isValidPlateNumber(plateNumber)) {
      validPlate = true;
    } else {
      Serial.println("❌ Invalid plate number! Must be 7 chars, start with 'RA', followed by an uppercase letter, 3 digits, and an uppercase letter (e.g., RAC500D).");
    }
    // Clear any leftover bytes
    while (Serial.available()) Serial.read();
  }

  Serial.println("Enter amount to add to balance (press Enter to keep current): ");
  while (!Serial.available()) {
    delay(10);
  }
  balanceToAdd = Serial.readStringUntil('\n');
  balanceToAdd.trim();

  // Handle empty input for balance
  if (balanceToAdd == "") {
    balanceToAdd = "[No Change]";
  }

  Serial.print("New Plate   : "); Serial.println(plateNumber);
  Serial.print("Amount to Add: "); Serial.println(balanceToAdd);

  // Clear buffer again
  while (Serial.available()) Serial.read();
}


// Validate that plate number is exactly 7 chars, starts with "RA", etc.
bool isValidPlateNumber(String str) {
  // Check length (exactly 7 characters)
  if (str.length() != 7) return false;

  // Check if starts with "RA"
  if (!str.startsWith("RA")) return false;

  // Check if third character (index 2) is an uppercase letter
  char thirdChar = str[2];
  if (!isalpha(thirdChar)) return false;
  if (!isupper(thirdChar)) return false;

  // Check if characters 4–6 (indices 3–5) are digits
  for (int i = 3; i <= 5; i++) {
    if (!isdigit(str[i])) return false;
  }

  // Check if last character is an uppercase letter
  char lastChar = str[6];
  if (!isalpha(lastChar)) return false;
  if (!isupper(lastChar)) return false;

  return true;
}


// ----------------- CHANGED FUNCTION -----------------
// Check if the given string can be parsed entirely as a float/double
bool isValidNumber(String str) {
  // Empty string or whitespace‐only → invalid
  if (str.length() == 0) return false;

  // Reject known sentinel strings
  if (str == "[Auth Failed]" || str == "[Read Failed]" || str == "[No Change]") {
    return false;
  }

  // Use strtod (available in AVR) to parse as a double
  char* endptr;
  double value = strtod(str.c_str(), &endptr);

  // If conversion didn't consume the entire string, it’s invalid
  if (endptr == str.c_str() || *endptr != '\0') {
    return false;
  }

  // Otherwise, it is a valid number
  return true;
}
// ----------------------------------------------------


// Write up to 16 bytes from data[] into blockNum using key A = {0xFF,...}
bool writeBlock(byte blockNum, const char* data) {
  byte buffer[16];
  memset(buffer, 0, 16);
  strncpy((char*)buffer, data, 16);

  MFRC522::MIFARE_Key key;
  for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF;

  // Authenticate using Key A
  MFRC522::StatusCode status = rfid.PCD_Authenticate(
    MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNum, &key, &savedUid
  );
  if (status != MFRC522::STATUS_OK) {
    Serial.print("Auth failed for block "); Serial.println(blockNum);
    return false;
  }

  // Write the 16‐byte buffer
  status = rfid.MIFARE_Write(blockNum, buffer, 16);
  if (status != MFRC522::STATUS_OK) {
    Serial.print("Write failed for block "); Serial.println(blockNum);
    return false;
  }

  return true;
}


// Read up to 16 bytes from blockNum, return as a String (stops at first zero‐byte)
String readBlockAsString(byte blockNum) {
  byte buffer[18];
  byte size = sizeof(buffer);
  String result = "";

  MFRC522::MIFARE_Key key;
  for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF;

  // Authenticate
  MFRC522::StatusCode status = rfid.PCD_Authenticate(
    MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNum, &key, &savedUid
  );
  if (status != MFRC522::STATUS_OK) {
    Serial.print("Auth failed for block "); Serial.println(blockNum);
    return "[Auth Failed]";
  }

  // Read the block (16 bytes + 2 CRC bytes)
  status = rfid.MIFARE_Read(blockNum, buffer, &size);
  if (status != MFRC522::STATUS_OK) {
    Serial.print("Read failed for block "); Serial.println(blockNum);
    return "[Read Failed]";
  }

  // Convert non‐zero bytes into characters
  for (int i = 0; i < 16; i++) {
    if (buffer[i] == 0) break;
    result += (char)buffer[i];
  }

  return result;
}
