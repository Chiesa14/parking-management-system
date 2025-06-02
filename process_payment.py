import sqlite3
import os
import time
import platform
import serial
import serial.tools.list_ports
from datetime import datetime

# Config
db_file = "data/parking.db"
RATE_PER_HOUR = 500  # RWF per hour
ser = None

# SQLite3 database setup
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
cursor.execute('''
CREATE TABLE IF NOT EXISTS transactions (
    plate_number TEXT,
    entry_time TEXT,
    exit_time TEXT,
    duration_hr REAL,
    amount INTEGER,
    payment_status INTEGER
)
''')
conn.commit()

def detect_arduino_port():
    ports = list(serial.tools.list_ports.comports())
    system = platform.system()

    for port in ports:
        port_name = port.device
        if (
            ("ttyACM" in port_name or "ttyUSB" in port_name) and system == "Linux" or
            ("usbmodem" in port_name or "wchusbserial" in port_name) and system == "Darwin" or
            ("COM" in port_name) and system == "Windows"
        ):
            return port_name
    return None

def listen_to_arduino(arduino_port, baud=115200):
    global ser
    try:
        ser = serial.Serial(arduino_port, baud, timeout=2)
        time.sleep(2)
        print(f"🔌 Listening on {arduino_port}...")

        while True:
            line = ser.readline().decode('utf-8').strip()
            if line:
                print("📨 Received:", line)
                process_message(line)

    except serial.SerialException as e:
        print("❌ Serial error:", e)
    except KeyboardInterrupt:
        print("\n🔚 Exiting...")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

def process_message(message):
    if "PLATE:" in message and "BALANCE:" in message:
        try:
            parts = message.split("|")
            plate = parts[0].split("PLATE:")[1]
            balance = int(parts[1].split("BALANCE:")[1])
            print(f"✅ Plate: {plate} | Balance: {balance} RWF")

            entry_time = lookup_entry_time(plate)
            if entry_time:
                compute_and_log_payment(plate, entry_time, balance)
            else:
                print("❌ Plate not found in log.")
        except Exception as e:
            print(f"⚠️ Failed to process message: {e}")
    else:
        print("⚠️ Unrecognized format.")

def lookup_entry_time(plate):
    cursor.execute("SELECT entry_timestamp FROM plates_log WHERE plate_number = ? ORDER BY entry_timestamp DESC LIMIT 1", (plate,))
    row = cursor.fetchone()
    if row:
        return datetime.fromisoformat(row[0])
    return None

def update_payment_status_in_log(plate, exit_time, action_type="EXIT"):
    cursor.execute("UPDATE plates_log SET payment_status = 1, exit_timestamp = ?, action_type = ? WHERE plate_number = ? AND payment_status = 0", (exit_time.isoformat(sep=' '), action_type, plate))
    conn.commit()
    print("📝 Updated plates_log with full exit info")

def compute_and_log_payment(plate, entry_time, balance):
    now = datetime.now()
    already_paid = False
    last_exit_time = None

    # Check last payment record
    cursor.execute("SELECT exit_timestamp FROM plates_log WHERE plate_number = ? AND payment_status = 1 ORDER BY entry_timestamp DESC LIMIT 1", (plate,))
    row = cursor.fetchone()
    if row:
        last_exit_time = datetime.fromisoformat(row[0])
        already_paid = True

    if already_paid:
        time_diff = (now - last_exit_time).total_seconds() / 60
        if time_diff <= 15:
            print("🕒 Already paid. Exit within 15 minutes, no extra charge.")
            return
        else:
            duration = now - last_exit_time
    else:
        duration = now - entry_time

    duration_hours = round(duration.total_seconds() / 3600, 2)
    
    # Round up to 1 hour if duration is less than 1 hour
    if duration_hours < 1:
        duration_hours = 1
        print("⏰ Duration less than 1 hour, charging base rate of 1 hour")
    
    amount_due = round(duration_hours * RATE_PER_HOUR)
    print(f"🕒 Duration: {duration_hours} hrs | 💸 Due: {amount_due} RWF")

    if balance < amount_due:
        print("❌ Insufficient balance!")
        return

    # Send payment command to Arduino
    command = f"PAY:{amount_due}\n"
    print(f"➡️ Sending command to Arduino: {command.strip()}")
    global ser
    ser.write(command.encode())
    ser.flush()

    response = ser.readline().decode().strip()
    if response == "DONE":
        print("✅ Payment completed by Arduino.")

        if not already_paid:
            update_payment_status_in_log(plate, now)

        # Log the transaction in the transactions table
        cursor.execute("INSERT INTO transactions (plate_number, entry_time, exit_time, duration_hr, amount, payment_status) VALUES (?, ?, ?, ?, ?, ?)",
                       (plate, entry_time.isoformat() if not already_paid else last_exit_time.isoformat(), now.isoformat(), duration_hours, amount_due, 1))
        conn.commit()

        # Update the exit timestamp and payment status in the plates_log table
        cursor.execute("UPDATE plates_log SET exit_timestamp = ?, payment_status = 1 WHERE plate_number = ? AND payment_status = 0", (now.isoformat(), plate))
        conn.commit()
    else:
        print(f"❌ Payment failed or no DONE signal: {response}")

if __name__ == "__main__":
    port = detect_arduino_port()
    if port:
        listen_to_arduino(port)
    else:
        print("❌ No Arduino port found.")
    conn.close()