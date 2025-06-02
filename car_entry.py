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
from datetime import datetime, timedelta

# Load YOLOv8 model
model = YOLO('best.pt')
# Plate save directory
save_dir = 'plates'
os.makedirs(save_dir, exist_ok=True)

# CSV log file
csv_file = 'data/plates_log.csv'
if not os.path.exists(csv_file):
    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Plate Number', 'Payment Status', 'Entry Timestamp', 'Exit Timestamp', 'Action Type'])


# ===== Auto-detect Arduino Serial Port =====
def detect_arduino_port():
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        if ("ttyACM" in port.device or  # Linux (native USB)
                "ttyUSB" in port.device or  # Linux (USB-serial)
                "usbmodem" in port.device or  # macOS (native USB)
                "wchusbserial" in port.device or  # macOS/Windows (CH340)
                "COM" in port.device):  # Windows
            return port.device
    return None


arduino_port = detect_arduino_port()
if arduino_port:
    print(f"[CONNECTED] Arduino on {arduino_port}")
    arduino = serial.Serial(arduino_port, 9600, timeout=1)
    time.sleep(2)
else:
    print("[ERROR] Arduino not detected.")
    arduino = None


# ===== Parking Validation Functions =====
def read_parking_log():
    """Read the current parking log and return as DataFrame"""
    try:
        if os.path.exists(csv_file):
            df = pd.read_csv(csv_file)
            return df
        else:
            return pd.DataFrame(
                columns=['Plate Number', 'Payment Status', 'Entry Timestamp', 'Exit Timestamp', 'Action Type'])
    except Exception as e:
        print(f"[ERROR] Reading CSV: {e}")
        return pd.DataFrame(
            columns=['Plate Number', 'Payment Status', 'Entry Timestamp', 'Exit Timestamp', 'Action Type'])


def is_vehicle_in_parking(plate_number):
    """Check if vehicle is currently in parking (entered but not exited)"""
    df = read_parking_log()
    if df.empty:
        return False

    # Get all records for this plate
    plate_records = df[df['Plate Number'] == plate_number]
    if plate_records.empty:
        return False

    # Check the most recent record
    latest_record = plate_records.iloc[-1]

    # Vehicle is in parking if:
    # 1. Action Type is 'ENTRY' and Exit Timestamp is empty/null
    # 2. OR Entry Timestamp is more recent than Exit Timestamp
    if latest_record['Action Type'] == 'ENTRY' and (
            pd.isna(latest_record['Exit Timestamp']) or latest_record['Exit Timestamp'] == ''):
        return True

    return False


def get_payment_status(plate_number):
    """Get the payment status of the vehicle currently in parking"""
    df = read_parking_log()
    if df.empty:
        return None

    # Get records for this plate that are currently in parking
    plate_records = df[df['Plate Number'] == plate_number]
    if plate_records.empty:
        return None

    # Find the most recent entry record
    entry_records = plate_records[plate_records['Action Type'] == 'ENTRY']
    if entry_records.empty:
        return None

    latest_entry = entry_records.iloc[-1]

    # Check if this entry has a corresponding exit
    entry_time = latest_entry['Entry Timestamp']
    exit_records = plate_records[
        (plate_records['Action Type'] == 'EXIT') &
        (plate_records['Entry Timestamp'] == entry_time)
        ]

    if exit_records.empty:  # No exit record, vehicle is still in parking
        return latest_entry['Payment Status']

    return None


def validate_entry(plate_number):
    """
    Validate if a vehicle can enter the parking
    Returns: (can_enter: bool, reason: str)
    """
    # Check if vehicle is already in parking
    if is_vehicle_in_parking(plate_number):
        payment_status = get_payment_status(plate_number)

        if payment_status == 0:  # Unpaid - cannot enter again
            return False, "DENIED: Vehicle already in parking with unpaid fees"
        elif payment_status == 1:  # Paid - should use exit system
            return False, "DENIED: Vehicle already in parking (use EXIT system)"
        else:
            return False, "DENIED: Vehicle status unclear"

    # Vehicle not in parking - can enter
    return True, "APPROVED: Vehicle can enter"


def log_entry(plate_number, payment_status=0):
    """Log vehicle entry to CSV"""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')

    with open(csv_file, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([plate_number, payment_status, timestamp, '', 'ENTRY'])

    print(f"[LOGGED] Entry: {plate_number} at {timestamp}")


def log_exit(plate_number):
    """Log vehicle exit and update the corresponding entry record"""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')

    # Read current log
    df = read_parking_log()

    # Find the most recent entry for this plate without an exit
    plate_entries = df[
        (df['Plate Number'] == plate_number) &
        (df['Action Type'] == 'ENTRY') &
        ((df['Exit Timestamp'].isna()) | (df['Exit Timestamp'] == ''))
        ]

    if not plate_entries.empty:
        # Update the most recent entry with exit timestamp
        latest_entry_idx = plate_entries.index[-1]
        df.at[latest_entry_idx, 'Exit Timestamp'] = timestamp

        # Save updated DataFrame
        df.to_csv(csv_file, index=False)

        # Also log a separate EXIT record for tracking
        with open(csv_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([plate_number, df.at[latest_entry_idx, 'Payment Status'],
                             df.at[latest_entry_idx, 'Entry Timestamp'], timestamp, 'EXIT'])

        print(f"[LOGGED] Exit: {plate_number} at {timestamp}")
    else:
        print(f"[ERROR] No entry record found for {plate_number}")


def control_gate(action, duration=15):
    """Control gate opening/closing"""
    if arduino:
        if action == "OPEN":
            arduino.write(b'1')
            print("[GATE] Opening gate")
            time.sleep(duration)
            arduino.write(b'0')
            print("[GATE] Closing gate")
        elif action == "CLOSE":
            arduino.write(b'0')
            print("[GATE] Gate closed")


def display_parking_status():
    """Display current parking status"""
    df = read_parking_log()
    if df.empty:
        print("[STATUS] No vehicles in parking")
        return

    # Count vehicles currently in parking
    vehicles_in_parking = 0
    unpaid_vehicles = 0

    # Get unique plates and check their status
    unique_plates = df['Plate Number'].unique()

    for plate in unique_plates:
        if is_vehicle_in_parking(plate):
            vehicles_in_parking += 1
            payment_status = get_payment_status(plate)
            if payment_status == 0:
                unpaid_vehicles += 1

    print(f"[STATUS] Vehicles in parking: {vehicles_in_parking}")
    print(f"[STATUS] Unpaid vehicles: {unpaid_vehicles}")


# ===== Ultrasonic Sensor Setup =====
import random


def mock_ultrasonic_distance():
    return random.choice([random.randint(10, 40)] + [random.randint(60, 150)] * 10)


# Initialize webcam
cap = cv2.VideoCapture(0)
plate_buffer = []
entry_cooldown = 300  # 5 minutes
last_saved_plate = None
last_entry_time = 0

print("[SYSTEM] Enhanced Parking Management System Ready")
print("[SYSTEM] Press 'q' to exit, 's' to show parking status")
display_parking_status()

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Check for status display request
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

                # Plate Image Processing
                gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
                blur = cv2.GaussianBlur(gray, (5, 5), 0)
                thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

                # OCR Extraction
                plate_text = pytesseract.image_to_string(
                    thresh, config='--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                ).strip().replace(" ", "")

                # Plate Validation
                if "RA" in plate_text:
                    start_idx = plate_text.find("RA")
                    plate_candidate = plate_text[start_idx:]
                    if len(plate_candidate) >= 7:
                        plate_candidate = plate_candidate[:7]
                        prefix, digits, suffix = plate_candidate[:3], plate_candidate[3:6], plate_candidate[6]
                        if (prefix.isalpha() and prefix.isupper() and
                                digits.isdigit() and suffix.isalpha() and suffix.isupper()):
                            print(f"[DETECTED] Plate: {plate_candidate}")
                            plate_buffer.append(plate_candidate)

                            # Decision after 3 captures
                            if len(plate_buffer) >= 3:
                                most_common = Counter(plate_buffer).most_common(1)[0][0]
                                current_time = time.time()

                                # Check cooldown to prevent duplicate processing
                                if (most_common != last_saved_plate or
                                        (current_time - last_entry_time) > entry_cooldown):

                                    # ===== ENTRY VALIDATION =====
                                    can_enter, reason = validate_entry(most_common)

                                    print(f"[VALIDATION] {reason}")

                                    if can_enter:
                                        # Log entry (new vehicles only)
                                        log_entry(most_common, payment_status=0)

                                        # Open gate for entry
                                        control_gate("OPEN", duration=15)

                                        print(f"[ENTRY] {most_common} entered parking")

                                        # Update tracking variables
                                        last_saved_plate = most_common
                                        last_entry_time = current_time

                                        # Display updated status
                                        display_parking_status()

                                    else:
                                        print(f"[DENIED] {most_common} - {reason}")
                                        # Optionally: sound alarm, send notification, etc.

                                else:
                                    print(f"[COOLDOWN] {most_common} - Too soon since last detection")

                                plate_buffer.clear()

                cv2.imshow("Plate", plate_img)
                cv2.imshow("Processed", thresh)
                time.sleep(0.5)

    # Display frame with annotations if plate detected
    if distance <= 50 and 'results' in locals():
        annotated_frame = results[0].plot()
    else:
        annotated_frame = frame

    cv2.imshow('Webcam Feed', annotated_frame)

print("[SYSTEM] Shutting down...")
cap.release()
if arduino:
    arduino.close()
cv2.destroyAllWindows()

# Final status display
print("\n[FINAL STATUS]")
display_parking_status()