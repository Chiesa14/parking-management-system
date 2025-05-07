import csv
import os
from datetime import datetime
import serial
import serial.tools.list_ports
import time
import platform

LOG_FILE = "plates_log.csv"
TX_FILE = "data/transactions.csv"
RATE_PER_HOUR = 200  # RWF per hour
ser = None

def listen_to_arduino(arduino_port, baud=9600):
    global  ser
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
                return datetime.fromisoformat(row['Timestamp'])
    return None

def update_payment_status_in_log(plate):
    rows = []
    with open(LOG_FILE, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if row['Plate Number'] == plate and row['Payment Status'] == '0':
                row['Payment Status'] = '1'
            rows.append(row)

    with open(LOG_FILE, "w", newline='') as csvfile:
        fieldnames = ['Plate Number', 'Payment Status', 'Timestamp']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print("📝 Updated plates_log.csv with payment_status = 1")



def compute_and_log_payment(plate, entry_time, balance):
    now = datetime.now()
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
    global ser  # reuse the open serial port
    ser.write(command.encode())

    # Wait for 'DONE'
    response = ser.readline().decode().strip()
    if response == "DONE":
        print("✅ Payment completed by Arduino.")

        # Update plates_log.csv (mark payment_status = 1)
        update_payment_status_in_log(plate)

        # Log transaction
        os.makedirs(os.path.dirname(TX_FILE), exist_ok=True)
        file_exists = os.path.isfile(TX_FILE)

        with open(TX_FILE, "a", newline='') as csvfile:
            fieldnames = ['plate_number', 'entry_time', 'exit_time', 'duration_hr', 'amount', 'payment_status']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            if not file_exists:
                writer.writeheader()

            writer.writerow({
                'plate_number': plate,
                'entry_time': entry_time.isoformat(),
                'exit_time': now.isoformat(),
                'duration_hr': duration_hours,
                'amount': amount_due,
                'payment_status': 1
            })
    else:
        print(f"❌ Payment failed or no DONE signal: {response}")

def find_serial_port():
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if "Arduino" in p.description or "CH340" in p.description or "ttyUSB" in p.device:
            return p.device
    return ports[0].device if ports else None

if __name__ == "__main__":
    port = find_serial_port()
    if port:
        listen_to_arduino(port)
    else:
        print("❌ No serial port found.")
