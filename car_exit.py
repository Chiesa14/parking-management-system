from datetime import datetime
import cv2
from ultralytics import YOLO
import pytesseract
import os
import time
import serial
import serial.tools.list_ports
import sqlite3
from collections import Counter
import random

# Load YOLOv8 model
model = YOLO('best3.pt')

# SQLite3 database setup
db_file = 'data/parking.db'
os.makedirs(os.path.dirname(db_file), exist_ok=True)
conn = sqlite3.connect(db_file)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS plates_log (
    plate_number TEXT,
    payment_status INTEGER,
    entry_timestamp TEXT,
    exit_timestamp TEXT,
    action_type TEXT
)
''')
conn.commit()

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
    cursor.execute("SELECT * FROM plates_log WHERE plate_number = ? AND payment_status = 1 ORDER BY entry_timestamp DESC LIMIT 1", (plate_number,))
    row = cursor.fetchone()
    if row:
        try:
            exit_time = datetime.fromisoformat(row[3])
            now = datetime.now()
            diff_minutes = (now - exit_time).total_seconds() / 60
            if diff_minutes <= 15:
                return True, "[✅] Payment valid. Exiting within 15 minutes."
            else:
                # Log unauthorized exit attempt
                log_unauthorized_exit(plate_number, "Payment expired")
                return False, "[⏱️] Payment expired. Please repay at kiosk."
        except Exception as e:
            # Log unauthorized exit attempt
            log_unauthorized_exit(plate_number, f"Error: {str(e)}")
            return False, f"[⚠️] Error parsing time: {e}"
    
    # Log unauthorized exit attempt
    log_unauthorized_exit(plate_number, "No payment found")
    return False, "[❌] No successful payment found."

def log_unauthorized_exit(plate_number, reason):
    """Log unauthorized exit attempt in the database"""
    timestamp = datetime.now().isoformat()
    cursor.execute('''
        INSERT INTO plates_log (plate_number, payment_status, entry_timestamp, exit_timestamp, action_type)
        VALUES (?, ?, ?, ?, ?)
    ''', (plate_number, 0, timestamp, timestamp, 'UNAUTHORIZED_EXIT'))
    conn.commit()
    print(f"[LOGGED] Unauthorized exit attempt: {plate_number} - {reason}")

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
                                    time.sleep(15)
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
conn.close()