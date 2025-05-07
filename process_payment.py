import serial
import serial.tools.list_ports
import time
import platform

def find_serial_port():
    ports = list(serial.tools.list_ports.comports())
    os_type = platform.system()

    print(f"🖥️ Detected OS: {os_type}")
    print("🔍 Searching for available serial ports...")

    for p in ports:
        port_name = p.device
        print(f"   ↪ Found port: {port_name} - {p.description}")

        # Optionally filter known Arduino boards by name
        if "Arduino" in p.description or "CH340" in p.description or "ttyUSB" in port_name:
            print(f"✅ Using port: {port_name}")
            return port_name

    # If none matched specifically, return the first one
    if ports:
        print(f"⚠️ Defaulting to first port: {ports[0].device}")
        return ports[0].device

    print("❌ No serial ports found.")
    return None

def listen_to_arduino(arduino_port, baud=9600):
    try:
        ser = serial.Serial(arduino_port, baud, timeout=2)
        time.sleep(2)  # Allow Arduino reset
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
    # Format: PLATE:XYZ|BALANCE:1234
    if "PLATE:" in message and "BALANCE:" in message:
        try:
            parts = message.split("|")
            plate = parts[0].split("PLATE:")[1]
            balance = parts[1].split("BALANCE:")[1]
            print(f"✅ Plate: {plate} | Balance: {balance}")

            # (Next steps: lookup, log, or process payment)

        except IndexError:
            print("⚠️ Error parsing message.")
    else:
        print("⚠️ Unrecognized format:", message)

if __name__ == "__main__":
    port = find_serial_port()
    if port:
        listen_to_arduino(port)
    else:
        print("🔌 Please connect your Arduino and try again.")
