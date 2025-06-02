from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import json
import threading
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")

def get_db_connection():
    conn = sqlite3.connect('data/parking.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/dashboard_data')
def dashboard_data():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS transactions
                   (
                       plate_number
                       TEXT,
                       entry_time
                       TEXT,
                       exit_time
                       TEXT,
                       duration_hr
                       REAL,
                       amount
                       INTEGER,
                       payment_status
                       INTEGER
                   )
                   ''')

    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS plates_log
                   (
                       plate_number
                       TEXT,
                       payment_status
                       INTEGER,
                       entry_timestamp
                       TEXT,
                       exit_timestamp
                       TEXT,
                       action_type
                       TEXT
                   )
                   ''')
    
    # Get current parking status
    cursor.execute('''
        SELECT 
            COUNT(*) as total_vehicles,
            SUM(CASE WHEN payment_status = 0 THEN 1 ELSE 0 END) as unpaid_vehicles,
            SUM(CASE WHEN payment_status = 1 THEN 1 ELSE 0 END) as paid_vehicles
        FROM plates_log
    ''')
    parking_status = dict(cursor.fetchone())
    
    # Get today's revenue
    cursor.execute('''
        SELECT COALESCE(SUM(amount), 0) as today_revenue
        FROM transactions
        WHERE date(exit_time) = date('now')
    ''')
    today_revenue = dict(cursor.fetchone())
    
    # Get recent transactions
    cursor.execute('''
        SELECT DISTINCT t.*, p.plate_number
        FROM transactions t
        JOIN plates_log p ON t.plate_number = p.plate_number
        ORDER BY t.exit_time DESC
        LIMIT 10
    ''')
    recent_transactions = [dict(row) for row in cursor.fetchall()]
    
    # Get unauthorized exit attempts
    cursor.execute('''
        SELECT plate_number, entry_timestamp, exit_timestamp, action_type
        FROM plates_log
        WHERE action_type = 'UNAUTHORIZED_EXIT'
        ORDER BY exit_timestamp DESC
        LIMIT 10
    ''')
    unauthorized_exits = [dict(row) for row in cursor.fetchall()]
    
    # Get hourly statistics for the last 24 hours
    cursor.execute('''
        SELECT 
            strftime('%H', entry_timestamp) as hour,
            COUNT(*) as entries
        FROM plates_log
        WHERE entry_timestamp >= datetime('now', '-24 hours')
        GROUP BY hour
        ORDER BY hour
    ''')
    hourly_stats = [dict(row) for row in cursor.fetchall()]
    
    # Create a complete 24-hour dataset
    complete_hourly_stats = []
    for hour in range(24):
        hour_str = f"{hour:02d}"
        # Find if we have data for this hour
        hour_data = next((stat for stat in hourly_stats if stat['hour'] == hour_str), None)
        complete_hourly_stats.append({
            'hour': hour_str,
            'entries': hour_data['entries'] if hour_data else 0
        })
    
    print(f"[DEBUG] Hourly stats: {complete_hourly_stats}")  # Debug print
    
    conn.close()
    
    return jsonify({
        'parking_status': parking_status,
        'today_revenue': today_revenue,
        'recent_transactions': recent_transactions,
        'unauthorized_exits': unauthorized_exits,
        'hourly_stats': complete_hourly_stats
    })

def monitor_database_changes():
    """Monitor database for changes and emit updates"""
    last_check = None
    
    while True:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get the latest timestamp from any change in the database
        cursor.execute('''
            SELECT 
                MAX(exit_timestamp) as last_exit,
                MAX(entry_timestamp) as last_entry,
                (SELECT COUNT(*) FROM plates_log WHERE action_type = 'UNAUTHORIZED_EXIT') as unauthorized_count,
                (SELECT MAX(exit_time) FROM transactions) as last_transaction
            FROM plates_log
        ''')
        result = cursor.fetchone()
        
        # Create a unique identifier for the current state
        current_state = (
            result['last_exit'] or '',
            result['last_entry'] or '',
            result['unauthorized_count'] or 0,
            result['last_transaction'] or ''
        )
        
        # If this is the first check or if there's been a change
        if last_check is None or current_state != last_check:
            print(f"[DEBUG] Database change detected: {current_state}")
            emit_parking_update()
            last_check = current_state
        
        conn.close()
        time.sleep(0.5)  # Check more frequently

def emit_parking_update():
    """Emit real-time parking updates to connected clients"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get latest entry/exit
        cursor.execute('''
            SELECT plate_number, entry_timestamp, exit_timestamp, action_type, payment_status
            FROM plates_log
            ORDER BY entry_timestamp DESC
            LIMIT 1
        ''')
        latest_activity = dict(cursor.fetchone())
        
        # Get current parking count
        cursor.execute('''
            SELECT 
                COUNT(*) as current_count,
                SUM(CASE WHEN payment_status = 0 THEN 1 ELSE 0 END) as unpaid_count
            FROM plates_log
            WHERE (exit_timestamp IS NULL OR exit_timestamp = '')
            AND action_type = 'ENTRY'
        ''')
        current_count = dict(cursor.fetchone())
        
        # Get latest unauthorized exits
        cursor.execute('''
            SELECT plate_number, entry_timestamp, exit_timestamp, action_type
            FROM plates_log
            WHERE action_type = 'UNAUTHORIZED_EXIT'
            ORDER BY exit_timestamp DESC
            LIMIT 10
        ''')
        unauthorized_exits = [dict(row) for row in cursor.fetchall()]
        
        # Get today's revenue and recent transactions
        cursor.execute('''
            SELECT COALESCE(SUM(amount), 0) as today_revenue
            FROM transactions
            WHERE date(exit_time) = date('now')
        ''')
        today_revenue = dict(cursor.fetchone())
        
        # Get recent transactions with unique entries
        cursor.execute('''
            SELECT DISTINCT t.*, p.plate_number
            FROM transactions t
            JOIN plates_log p ON t.plate_number = p.plate_number
            ORDER BY t.exit_time DESC
            LIMIT 10
        ''')
        recent_transactions = [dict(row) for row in cursor.fetchall()]
        
        update_data = {
            'latest_activity': latest_activity,
            'current_count': current_count,
            'unauthorized_exits': unauthorized_exits,
            'today_revenue': today_revenue,
            'recent_transactions': recent_transactions
        }
        
        print(f"[DEBUG] Emitting update: {update_data}")
        socketio.emit('parking_update', update_data)
        
    except Exception as e:
        print(f"[ERROR] Failed to emit update: {e}")
    finally:
        conn.close()

@socketio.on('connect')
def handle_connect():
    print("[DEBUG] New client connected")
    emit_parking_update()

@socketio.on('disconnect')
def handle_disconnect():
    print("[DEBUG] Client disconnected")

if __name__ == '__main__':
    # Start the database monitoring thread
    monitor_thread = threading.Thread(target=monitor_database_changes, daemon=True)
    monitor_thread.start()
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000,allow_unsafe_werkzeug=True)