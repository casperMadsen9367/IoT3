import sys
sys.path.append('/home/casp/Desktop/myenv/lib/python3.11/site-packages')

import subprocess
import sqlite3
from flask import Flask, render_template, jsonify
import threading
import time
from queue import Queue, Empty
import vonage


app = Flask(__name__)

mqtt_broker = "10.10.10.10"
temperature_topic = "sensor/temperature"
humidity_topic = "sensor/humidity"
fall_topic = "sensor/fall"


temperature_command = f"mosquitto_sub -h {mqtt_broker} -t {temperature_topic}"
humidity_command = f"mosquitto_sub -h {mqtt_broker} -t {humidity_topic}"
fall_command = f"mosquitto_sub -h {mqtt_broker} -t {fall_topic}"

def create_table():
    conn = sqlite3.connect('sensor_data.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS borger1 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            temperature REAL,
            humidity REAL,
            fall REAL,
            timestamp DATETIME DEFAULT (strftime('%Y-%m-%d %H:%M:%S', datetime('now', 'localtime')))
        )
    ''')
    conn.commit()

    conn.close()

@app.route('/')
def index():
    create_table()

    conn = sqlite3.connect('sensor_data.db')
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'sensor_data';")
    tables = [table[0] for table in cursor.fetchall()]

    cursor.execute("SELECT fall FROM borger1 ORDER BY timestamp DESC;")
    fall_data = cursor.fetchall()

    conn.close()

    return render_template('index.html', tables=tables, fall_data=fall_data)

@app.route('/fall_data')
def get_fall_data():
    conn = sqlite3.connect('sensor_data.db')
    cursor = conn.cursor()

    cursor.execute("SELECT fall FROM borger1 ORDER BY timestamp DESC LIMIT 1;")
    fall_data = cursor.fetchone()

    conn.close()

    return jsonify({'fall_data': fall_data[0] if fall_data else None})

@app.route('/table/<table_name>')
def show_table(table_name):
    table_name = 'borger1'
    create_table()

    conn = sqlite3.connect('sensor_data.db')
    cursor = conn.cursor()

    cursor.execute(f"SELECT * FROM {table_name} ORDER BY timestamp DESC;")
    data = cursor.fetchall()

    conn.close()

    return render_template('table.html', table_name=table_name, data=data)

def run_mosquitto_sub(command):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    while True:
        output = process.stdout.readline()
        if output == b'' and process.poll() is not None:
            break
        if output:
            yield float(output.decode('utf-8').strip())

def get_next_table_name():
    conn = sqlite3.connect('sensor_data.db')
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'sensor_data';")
    num_tables = cursor.fetchone()[0]

    conn.close()

    return f'table_{num_tables + 1}'

def mqtt_data_collection(temperature_command, humidity_command, fall_command):
    create_table()
    fall = None
    while True:

        conn = sqlite3.connect('sensor_data.db')
        cursor = conn.cursor()

        create_table()

        queue_temperature = Queue()
        queue_humidity = Queue()
        queue_fall = Queue()

        def fetch_temperature():
            for value in run_mosquitto_sub(temperature_command):
                queue_temperature.put(value)

        def fetch_humidity():
            for value in run_mosquitto_sub(humidity_command):
                queue_humidity.put(value)

        def fetch_fall():
            for value in run_mosquitto_sub(fall_command):
                queue_fall.put(value)

        thread_temperature = threading.Thread(target=fetch_temperature)
        thread_humidity = threading.Thread(target=fetch_humidity)
        thread_fall = threading.Thread(target=fetch_fall)

        thread_temperature.start()
        thread_humidity.start()
        thread_fall.start()

        while True:
            try:
                temperature = queue_temperature.get_nowait()
                humidity = queue_humidity.get_nowait()

                print(f'Temperature: {temperature}')
                print(f'Humidity: {humidity}')

                try:
                    fall = queue_fall.get_nowait()
                    print(f'Fall: {fall}')
                except Empty:
                    pass 

                cursor.execute(f"INSERT INTO borger1 (temperature, humidity, fall) VALUES (?, ?, ?)",
                               (temperature if temperature else None,
                                humidity if humidity else None,
                                fall if fall else None))
                conn.commit()

            except Empty:
                pass

            if not (thread_temperature.is_alive() or thread_humidity.is_alive() or thread_fall.is_alive()):
                break

        conn.close()


if __name__ == '__main__':
    flask_thread = threading.Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 5000})
    flask_thread.start()

    mqtt_thread = threading.Thread(target=mqtt_data_collection, args=(temperature_command, humidity_command, fall_command))
    mqtt_thread.start()

    try:
        flask_thread.join()
        mqtt_thread.join()
    except KeyboardInterrupt:
        conn = sqlite3.connect('sensor_data.db')
        conn.close()
