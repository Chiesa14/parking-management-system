import csv
import os
import time
import platform
import serial
import serial.tools.list_ports
from datetime import datetime

# Config
LOG_FILE = "data/plates_log.csv"
TX_FILE = "data/transactions.csv"
RATE_PER_HOUR = 500  # RWF per hour
ser = None

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
    if not os.path.exists(LOG_FILE):
        return None

    with open(LOG_FILE, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if row['Plate Number'] == plate and row['Payment Status'] == '0':
                return datetime.fromisoformat(row['Entry Timestamp'])
    return None

def update_payment_status_in_log(plate, exit_time, action_type="EXIT"):
    rows = []
    updated = False
    with open(LOG_FILE, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if row['Plate Number'] == plate and row['Payment Status'] == '0':
                row['Payment Status'] = '1'
                row['Exit Timestamp'] = exit_time.isoformat(sep=' ')
                row['Action Type'] = action_type
                updated = True
            rows.append(row)

    if updated:
        with open(LOG_FILE, "w", newline='') as csvfile:
            fieldnames = ['Plate Number', 'Payment Status', 'Entry Timestamp', 'Exit Timestamp', 'Action Type']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        print("📝 Updated plates_log.csv with full exit info")
    else:
        print("⚠️ No matching unpaid plate record found to update")

def compute_and_log_payment(plate, entry_time, balance):
    now = datetime.now()
    already_paid = False
    last_exit_time = None

    # Check last payment record
    if os.path.exists(TX_FILE):
        with open(TX_FILE, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reversed(list(reader)):
                if row['plate_number'] == plate:
                    last_exit_time = datetime.fromisoformat(row['exit_time'])
                    already_paid = True
                    break

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

        # Log the transaction
        os.makedirs(os.path.dirname(TX_FILE), exist_ok=True)
        file_exists = os.path.isfile(TX_FILE)

        with open(TX_FILE, "a", newline='') as csvfile:
            fieldnames = ['plate_number', 'entry_time', 'exit_time', 'duration_hr', 'amount', 'payment_status']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()

            writer.writerow({
                'plate_number': plate,
                'entry_time': entry_time.isoformat() if not already_paid else last_exit_time.isoformat(),
                'exit_time': now.isoformat(),
                'duration_hr': duration_hours,
                'amount': amount_due,
                'payment_status': 1
            })
    else:
        print(f"❌ Payment failed or no DONE signal: {response}")

if __name__ == "__main__":
    port = detect_arduino_port()
    if port:
        listen_to_arduino(port)
    else:
        print("❌ No Arduino port found.")