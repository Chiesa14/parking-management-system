from datetime import datetime
import cv2
from ultralytics import YOLO
import pytesseract
import os
import time
import serial
import serial.tools.list_ports
import csv
from collections import Counter
import random

# Load YOLOv8 model
model = YOLO('best3.pt')

# CSV Files
csv_file = 'data/plates_log.csv'
transactions_file = 'data/transactions.csv'


# ===== Detect Arduino Port =====
def detect_arduino_port():
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        if ("ttyACM" in port.device or
                "ttyUSB" in port.device or
                "usbmodem" in port.device or
                "wchusbserial" in port.device or
                "COM" in port.device):
            return port.device
    return None


arduino_port = detect_arduino_port()
if arduino_port:
    print(f"[CONNECTED] Arduino on {arduino_port}")
    # Optimized serial settings for minimal latency
    arduino = serial.Serial(
        arduino_port,
        115200,  # Higher baud rate
        timeout=0.1,  # Shorter timeout
        write_timeout=0.1,  # Write timeout
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE
    )
    # Clear any existing data in buffers
    arduino.reset_input_buffer()
    arduino.reset_output_buffer()
    time.sleep(1)  # Reduced wait time
else:
    print("[ERROR] Arduino not detected.")
    arduino = None


# ===== Fast Arduino Communication =====
def send_arduino_command(command):
    """Send command to Arduino with minimal latency"""
    if arduino:
        try:
            arduino.write(command.encode())
            arduino.flush()  # Force immediate transmission
            return True
        except Exception as e:
            print(f"[ERROR] Arduino communication failed: {e}")
            return False
    return False


# ===== Mock Sensor =====
def mock_ultrasonic_distance():
    return random.choice([random.randint(10, 40)] + [random.randint(60, 150)] * 10)


# ===== Check Payment Status =====
def is_payment_complete(plate_number):
    if not os.path.exists(transactions_file):
        return False, "[❌] No transaction history found."

    with open(transactions_file, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for row in reversed(rows):
        if row['plate_number'] == plate_number and row['payment_status'] == '1':
            try:
                exit_time = datetime.fromisoformat(row['exit_time'])
                now = datetime.now()
                diff_minutes = (now - exit_time).total_seconds() / 60
                if diff_minutes <= 15:
                    return True, "[✅] Payment valid. Exiting within 15 minutes."
                else:
                    return False, "[⏱️] Payment expired. Please repay at kiosk."
            except Exception as e:
                return False, f"[⚠️] Error parsing time: {e}"

    return False, "[❌] No successful payment found."


# ===== Main Loop =====
cap = cv2.VideoCapture(0)
plate_buffer = []
denied_plates = {}  # {plate: last_denied_timestamp}
BUZZER_DURATION = 5  # seconds
DENY_RETRY_DELAY = 60  # seconds before re-check allowed

print("[EXIT SYSTEM] Ready. Press 'q' to quit.")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    distance = mock_ultrasonic_distance()
    print(f"[SENSOR] Distance: {distance} cm")

    # ==== Plate detection logic ====
    if distance <= 50:
        results = model(frame)
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                plate_img = frame[y1:y2, x1:x2]

                gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
                blur = cv2.GaussianBlur(gray, (5, 5), 0)
                thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

                plate_text = pytesseract.image_to_string(
                    thresh, config='--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                ).strip().replace(" ", "")

                if "RA" in plate_text:
                    start_idx = plate_text.find("RA")
                    plate_candidate = plate_text[start_idx:]

                    if len(plate_candidate) >= 7:
                        plate_candidate = plate_candidate[:7]
                        prefix, digits, suffix = plate_candidate[:3], plate_candidate[3:6], plate_candidate[6]

                        if (prefix.isalpha() and prefix.isupper() and
                                digits.isdigit() and suffix.isalpha() and suffix.isupper()):

                            print(f"[VALID] Plate Detected: {plate_candidate}")

                            # Check if plate was recently denied
                            now = time.time()
                            if (plate_candidate in denied_plates and
                                    now - denied_plates[plate_candidate] < DENY_RETRY_DELAY):
                                print(f"[BLOCKED] {plate_candidate} already denied recently.")
                                continue

                            plate_buffer.append(plate_candidate)

                            if len(plate_buffer) >= 3:
                                most_common = Counter(plate_buffer).most_common(1)[0][0]
                                plate_buffer.clear()

                                is_paid, message = is_payment_complete(most_common)
                                print(message)

                                if is_paid:
                                    print(f"[ACCESS GRANTED] Payment complete for {most_common}")
                                    send_arduino_command('1')  # Open gate
                                    print("[GATE] Opening gate (sent '1')")
                                    time.sleep(15)  # Keep gate open for 15 seconds
                                    send_arduino_command('0')  # Close gate
                                    print("[GATE] Closing gate (sent '0')")
                                else:
                                    print(f"[ACCESS DENIED] Payment NOT complete or expired for {most_common}")
                                    denied_plates[most_common] = time.time()

                                    # Send buzzer command immediately
                                    send_arduino_command('D')
                                    print("[ALERT] Buzzer triggered (sent 'D')")

                                    # Wait 15 seconds after buzzer starts
                                    print("[SYSTEM] Waiting 15 seconds after buzzer...")
                                    time.sleep(5)
                                    print("[SYSTEM] 15 second wait complete")

                cv2.imshow("Plate", plate_img)
                cv2.imshow("Processed", thresh)
                # Reduced sleep to minimize delays
                time.sleep(0.1)

    # Display the frame
    if distance <= 50 and 'results' in locals():
        annotated_frame = results[0].plot()
    else:
        annotated_frame = frame

    cv2.imshow("Exit Webcam Feed", annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
if arduino:
    arduino.close()
cv2.destroyAllWindows()