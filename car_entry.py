import cv2
from ultralytics import YOLO
import pytesseract
import os
import time
import serial
import serial.tools.list_ports
import csv
from collections import Counter
import pandas as pd
from datetime import datetime
import random
import sqlite3

# Load YOLOv8 model
model = YOLO('best3.pt')
save_dir = 'plates'
os.makedirs(save_dir, exist_ok=True)

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

def detect_arduino_port():
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        if any(x in port.device for x in ["ttyACM", "ttyUSB", "usbmodem", "wchusbserial", "COM"]):
            return port.device
    return None

arduino_port = detect_arduino_port()
arduino = None
if arduino_port:
    try:
        # Optimized serial settings for minimal latency
        arduino = serial.Serial(
            arduino_port, 
            115200,  # Higher baud rate (matches Arduino)
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
        print(f"[CONNECTED] Arduino on {arduino_port}")
    except Exception as e:
        print(f"[ERROR] Could not open Arduino serial port: {e}")
else:
    print("[ERROR] Arduino not detected.")


def send_arduino_command(command):
    """Send command to Arduino with minimal latency"""
    if arduino:
        try:
            arduino.write(command.encode())
            arduino.flush()  # Force immediate transmission
            print(f"[ARDUINO] Sent: {command}")
            return True
        except Exception as e:
            print(f"[ERROR] Arduino communication failed: {e}")
            return False
    return False


def buzz(code):
    """Optimized buzzer function with immediate response"""
    if send_arduino_command(code):
        print(f"[BUZZER] Triggered: {code}")
        time.sleep(5)  # Wait for buzzer pattern to complete
    else:
        print(f"[ERROR] Failed to trigger buzzer: {code}")


def read_parking_log():
    cursor.execute("SELECT * FROM plates_log")
    rows = cursor.fetchall()
    return pd.DataFrame(rows, columns=['Plate Number', 'Payment Status', 'Entry Timestamp', 'Exit Timestamp', 'Action Type'])


def is_vehicle_in_parking(plate_number):
    cursor.execute("SELECT * FROM plates_log WHERE plate_number = ? ORDER BY entry_timestamp DESC LIMIT 1", (plate_number,))
    row = cursor.fetchone()
    if row:
        return row[4] == 'ENTRY' and (row[3] is None or row[3] == '')
    return False


def get_payment_status(plate_number):
    cursor.execute("SELECT * FROM plates_log WHERE plate_number = ? AND action_type = 'ENTRY' ORDER BY entry_timestamp DESC LIMIT 1", (plate_number,))
    entry_row = cursor.fetchone()
    if entry_row:
        entry_time = entry_row[2]
        cursor.execute("SELECT * FROM plates_log WHERE plate_number = ? AND action_type = 'EXIT' AND entry_timestamp = ?", (plate_number, entry_time))
        exit_row = cursor.fetchone()
        if exit_row:
            return None
        return entry_row[1]
    return None


def validate_entry(plate_number):
    if is_vehicle_in_parking(plate_number):
        status = get_payment_status(plate_number)
        if status == 0:
            buzz('D')  # Denied access pattern (fast urgent beeps)
            print("[VALIDATION] DENIED: Vehicle already in parking with unpaid fees")
            time.sleep(15)  # Sleep after denial buzzer to alert the driver
            return False, "DENIED: Vehicle already in parking with unpaid fees"
        elif status == 1:
            buzz('P')  # Already paid pattern
            print("[VALIDATION] DENIED: Vehicle already in parking (use EXIT system)")
            time.sleep(15)  # Optional: also delay after this buzzer
            return False, "DENIED: Vehicle already in parking (use EXIT system)"
        else:
            buzz('D')  # Unknown status - treat as denied
            print("[VALIDATION] DENIED: Vehicle status unclear")
            time.sleep(15)  # Sleep here too for unknown status
            return False, "DENIED: Vehicle status unclear"
    return True, "APPROVED: Vehicle can enter"


def log_entry(plate_number, payment_status=0):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO plates_log (plate_number, payment_status, entry_timestamp, exit_timestamp, action_type) VALUES (?, ?, ?, ?, ?)",
                   (plate_number, payment_status, timestamp, '', 'ENTRY'))
    conn.commit()
    print(f"[LOGGED] Entry: {plate_number} at {timestamp}")


def log_exit(plate_number):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("SELECT * FROM plates_log WHERE plate_number = ? AND action_type = 'ENTRY' AND (exit_timestamp IS NULL OR exit_timestamp = '') ORDER BY entry_timestamp DESC LIMIT 1", (plate_number,))
    entry_row = cursor.fetchone()
    if entry_row:
        cursor.execute("UPDATE plates_log SET exit_timestamp = ? WHERE plate_number = ? AND entry_timestamp = ? AND action_type = 'ENTRY'",
                       (timestamp, plate_number, entry_row[2]))
        cursor.execute("INSERT INTO plates_log (plate_number, payment_status, entry_timestamp, exit_timestamp, action_type) VALUES (?, ?, ?, ?, ?)",
                       (plate_number, entry_row[1], entry_row[2], timestamp, 'EXIT'))
        conn.commit()
        print(f"[LOGGED] Exit: {plate_number} at {timestamp}")
    else:
        print(f"[ERROR] No entry record found for {plate_number}")


def control_gate(action, duration=15):
    """Optimized gate control with immediate response"""
    if action == "OPEN":
        if send_arduino_command('1'):  # Open gate
            print("[GATE] Opening gate...")
            time.sleep(duration)  # Keep gate open
            send_arduino_command('0')  # Close gate
            print("[GATE] Closing gate...")
        else:
            print("[ERROR] Failed to control gate")


def display_parking_status():
    df = read_parking_log()
    unique_plates = df['Plate Number'].unique()
    in_parking = sum(is_vehicle_in_parking(p) for p in unique_plates)
    unpaid = sum(get_payment_status(p) == 0 for p in unique_plates if is_vehicle_in_parking(p))
    print(f"[STATUS] Vehicles in parking: {in_parking}")
    print(f"[STATUS] Unpaid vehicles: {unpaid}")


def mock_ultrasonic_distance():
    return random.choice([random.randint(10, 40)] + [random.randint(60, 150)] * 10)


# ===== Main Loop =====
cap = cv2.VideoCapture(0)
plate_buffer = []
entry_cooldown = 300
last_saved_plate = None
last_entry_time = 0

print("[SYSTEM] Smart Parking Entry System Ready")
display_parking_status()

while True:
    ret, frame = cap.read()
    if not ret:
        break

    key = cv2.waitKey(1) & 0xFF
    if key == ord('s'):
        display_parking_status()
        continue
    elif key == ord('q'):
        break

    distance = mock_ultrasonic_distance()
    print(f"[SENSOR] Distance: {distance} cm")

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
                    plate_candidate = plate_text[start_idx:start_idx + 7]
                    if len(plate_candidate) == 7:
                        prefix, digits, suffix = plate_candidate[:3], plate_candidate[3:6], plate_candidate[6]
                        if prefix.isalpha() and digits.isdigit() and suffix.isalpha():
                            print(f"[DETECTED] Plate: {plate_candidate}")
                            plate_buffer.append(plate_candidate)

                            if len(plate_buffer) >= 3:
                                most_common = Counter(plate_buffer).most_common(1)[0][0]
                                current_time = time.time()

                                if most_common != last_saved_plate or (current_time - last_entry_time) > entry_cooldown:
                                    can_enter, reason = validate_entry(most_common)
                                    print(f"[VALIDATION] {reason}")
                                    if can_enter:
                                        log_entry(most_common)
                                        control_gate("OPEN", duration=15)
                                        last_saved_plate = most_common
                                        last_entry_time = current_time
                                        display_parking_status()
                                else:
                                    print(f"[COOLDOWN] Skipped {most_common}")
                                plate_buffer.clear()

                cv2.imshow("Plate", plate_img)
                cv2.imshow("Processed", thresh)
                time.sleep(0.1)  # Reduced sleep time for faster processing

    annotated_frame = results[0].plot() if distance <= 50 and 'results' in locals() else frame
    cv2.imshow('Entry Webcam Feed', annotated_frame)

print("[SYSTEM] Shutting down...")
cap.release()
if arduino:
    arduino.close()
cv2.destroyAllWindows()
display_parking_status()
conn.close()