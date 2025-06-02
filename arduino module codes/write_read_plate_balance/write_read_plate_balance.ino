#include <SPI.h>
#include <MFRC522.h>
#include <stdlib.h>

#define SS_PIN 10
#define RST_PIN 9
#define BAUD_RATE 115200  // Increased baud rate for faster communication

MFRC522 rfid(SS_PIN, RST_PIN);
MFRC522::Uid savedUid;

String plateNumber = "";
String balanceToAdd = "";
bool processingPayment = false;

void setup() {
  Serial.begin(BAUD_RATE);
  while (!Serial) {
    ; // Wait for serial port to connect
  }
  
  SPI.begin();
  rfid.PCD_Init();
  
  Serial.println("📟 RFID Parking System Ready");
  Serial.println("🚀 High-speed mode enabled");
  Serial.println("Enter 'q' to quit, 'r' to read card");
  Serial.flush();
}

void loop() {
  // Handle incoming serial commands from Python
  handleSerialCommands();
  
  // Handle RFID card detection
  handleRFIDCards();
  
  // Small delay to prevent overwhelming the system
  delay(10);
}

void handleSerialCommands() {
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    
    if (command.startsWith("PAY:")) {
      handlePaymentCommand(command);
    }
    else if (command.startsWith("INSUFFICIENT_BALANCE:")) {
      handleInsufficientBalance(command);
    }
    else if (command.equalsIgnoreCase("q")) {
      Serial.println("🛑 System shutting down...");
      Serial.flush();
      while (true); // Stop execution
    }
    else if (command.equalsIgnoreCase("r")) {
      Serial.println("📖 Ready to read RFID card...");
    }
    
    // Clear any remaining buffer
    while (Serial.available()) Serial.read();
  }
}

void handlePaymentCommand(String command) {
  processingPayment = true;
  
  // Extract amount from command: "PAY:200"
  int colonIndex = command.indexOf(':');
  if (colonIndex == -1) {
    Serial.println("PAYMENT_FAILED");
    Serial.flush();
    processingPayment = false;
    return;
  }
  
  String amountStr = command.substring(colonIndex + 1);
  float amount = amountStr.toFloat();
  
  Serial.print("💳 Processing payment of ");
  Serial.print(amount, 2);
  Serial.println(" RWF...");
  
  // Simulate payment processing (in real implementation, this would deduct from RFID card)
  bool paymentSuccess = processPaymentOnCard(amount);
  
  if (paymentSuccess) {
    Serial.println("PAYMENT_SUCCESS");
    Serial.print("✅ Payment of ");
    Serial.print(amount, 2);
    Serial.println(" RWF completed");
  } else {
    Serial.println("PAYMENT_FAILED");
    Serial.println("❌ Payment processing failed");
  }
  
  Serial.flush();
  processingPayment = false;
}

void handleInsufficientBalance(String command) {
  // Parse: "INSUFFICIENT_BALANCE:200:150"
  int firstColon = command.indexOf(':');
  int secondColon = command.indexOf(':', firstColon + 1);
  
  if (firstColon != -1 && secondColon != -1) {
    String amountDue = command.substring(firstColon + 1, secondColon);
    String currentBalance = command.substring(secondColon + 1);
    
    Serial.print("⚠️ Insufficient balance! Need: ");
    Serial.print(amountDue);
    Serial.print(" RWF, Have: ");
    Serial.print(currentBalance);
    Serial.println(" RWF");
  }
  Serial.flush();
}

bool processPaymentOnCard(float amount) {
  // This function would typically:
  // 1. Read current balance from RFID card
  // 2. Deduct the payment amount
  // 3. Write new balance back to card
  // 4. Return success/failure status
  
  // For now, simulate the process
  delay(100); // Simulate processing time
  
  // In a real implementation, you would:
  // - Authenticate with the current card
  // - Read balance from block 4
  // - Subtract amount
  // - Write new balance back
  // - Verify the write operation
  
  return true; // Assume success for simulation
}

void handleRFIDCards() {
  // Skip RFID processing if we're handling a payment
  if (processingPayment) {
    return;
  }
  
  // Improved card detection with reduced delays
  if (!rfid.PICC_IsNewCardPresent()) {
    return;
  }

  if (!rfid.PICC_ReadCardSerial()) {
    return;
  }

  // Save UID for authentication
  savedUid = rfid.uid;

  // Read existing data from blocks
  String currentPlate = readBlockAsString(2);
  String currentBalance = readBlockAsString(4);

  // Send plate and balance info to Python immediately
  if (currentPlate.length() > 0 && currentBalance.length() > 0) {
    Serial.print("PLATE:");
    Serial.print(currentPlate);
    Serial.print("|BALANCE:");
    Serial.println(currentBalance);
    Serial.flush();
  }

  // Display current data locally
  Serial.println("\n📄 RFID Card Data:");
  Serial.print("Plate: "); Serial.println(currentPlate);
  Serial.print("Balance: "); Serial.println(currentBalance);

  // Ask for updates with timeout
  Serial.println("Update data? (y/n) - 5s timeout");
  Serial.flush();
  
  unsigned long startTime = millis();
  char decision = '\0';
  
  while (millis() - startTime < 5000) { // 5 second timeout
    if (Serial.available()) {
      decision = tolower(Serial.read());
      break;
    }
    delay(10);
  }
  
  // Clear buffer
  while (Serial.available()) Serial.read();

  if (decision == 'y') {
    getUserInputWithTimeout();
    updateCardData(currentPlate, currentBalance);
  } else {
    Serial.println("No update performed");
  }

  // Properly release the card
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  
  Serial.println("🔄 Ready for next operation...");
  Serial.flush();
}

void getUserInputWithTimeout() {
  plateNumber = "";
  balanceToAdd = "";

  // Get plate number with validation and timeout
  Serial.println("New plate (Enter to skip, 10s timeout):");
  Serial.flush();
  
  unsigned long startTime = millis();
  while (millis() - startTime < 10000) {
    if (Serial.available()) {
      plateNumber = Serial.readStringUntil('\n');
      plateNumber.trim();
      break;
    }
    delay(10);
  }

  if (plateNumber.length() == 0) {
    plateNumber = "[No Change]";
  } else if (!isValidPlateNumber(plateNumber)) {
    Serial.println("❌ Invalid plate format! Using existing...");
    plateNumber = "[No Change]";
  }

  // Get balance with timeout
  Serial.println("Amount to add (Enter to skip, 10s timeout):");
  Serial.flush();
  
  startTime = millis();
  while (millis() - startTime < 10000) {
    if (Serial.available()) {
      balanceToAdd = Serial.readStringUntil('\n');
      balanceToAdd.trim();
      break;
    }
    delay(10);
  }

  if (balanceToAdd.length() == 0) {
    balanceToAdd = "[No Change]";
  }

  // Clear any remaining buffer
  while (Serial.available()) Serial.read();
  
  Serial.print("Plate: "); Serial.println(plateNumber);
  Serial.print("Amount: "); Serial.println(balanceToAdd);
  Serial.flush();
}

void updateCardData(String currentPlate, String currentBalance) {
  // Update plate number if provided and valid
  if (plateNumber != "" && plateNumber != "[No Change]") {
    if (writeBlock(2, plateNumber.c_str())) {
      Serial.println("✅ Plate updated");
    } else {
      Serial.println("❌ Plate update failed");
    }
  }

  // Update balance if valid
  if (balanceToAdd != "" && balanceToAdd != "[No Change]") {
    float newBalance;
    bool isValidBalance = isValidNumber(currentBalance);

    if (isValidBalance) {
      float currentBalanceValue = currentBalance.toFloat();
      float amountToAdd = balanceToAdd.toFloat();
      newBalance = currentBalanceValue + amountToAdd;
    } else {
      newBalance = balanceToAdd.toFloat();
    }

    char newBalanceStr[16];
    dtostrf(newBalance, 0, 2, newBalanceStr);

    if (writeBlock(4, newBalanceStr)) {
      Serial.println("✅ Balance updated");
    } else {
      Serial.println("❌ Balance update failed");
    }
  }

  // Show final data
  Serial.println("🔁 Updated data:");
  Serial.print("Plate: "); Serial.println(readBlockAsString(2));
  Serial.print("Balance: "); Serial.println(readBlockAsString(4));
  Serial.flush();
}

bool isValidPlateNumber(String str) {
  if (str.length() != 7) return false;
  if (!str.startsWith("RA")) return false;
  
  char thirdChar = str[2];
  if (!isalpha(thirdChar) || !isupper(thirdChar)) return false;

  for (int i = 3; i <= 5; i++) {
    if (!isdigit(str[i])) return false;
  }

  char lastChar = str[6];
  if (!isalpha(lastChar) || !isupper(lastChar)) return false;

  return true;
}

bool isValidNumber(String str) {
  if (str.length() == 0) return false;
  if (str == "[Auth Failed]" || str == "[Read Failed]" || str == "[No Change]") {
    return false;
  }

  char* endptr;
  double value = strtod(str.c_str(), &endptr);
  
  if (endptr == str.c_str() || *endptr != '\0') {
    return false;
  }

  return true;
}

bool writeBlock(byte blockNum, const char* data) {
  byte buffer[16];
  memset(buffer, 0, 16);
  strncpy((char*)buffer, data, 15); // Leave room for null terminator

  MFRC522::MIFARE_Key key;
  for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF;

  MFRC522::StatusCode status = rfid.PCD_Authenticate(
    MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNum, &key, &savedUid
  );
  
  if (status != MFRC522::STATUS_OK) {
    return false;
  }

  status = rfid.MIFARE_Write(blockNum, buffer, 16);
  return (status == MFRC522::STATUS_OK);
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
    return "[Auth Failed]";
  }

  status = rfid.MIFARE_Read(blockNum, buffer, &size);
  if (status != MFRC522::STATUS_OK) {
    return "[Read Failed]";
  }

  for (int i = 0; i < 16; i++) {
    if (buffer[i] == 0) break;
    result += (char)buffer[i];
  }

  return result;
}
