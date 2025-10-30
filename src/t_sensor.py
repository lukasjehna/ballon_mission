# Complete Project Details: https://RandomNerdTutorials.com/raspberry-pi-ds18b20-python/

# Based on the Adafruit example: https://github.com/adafruit/Adafruit_Learning_System_Guides/blob/main/Raspberry_Pi_DS18B20_Temperature_Sensing/code.py
#use any number of temperature sensors
import os
import time
import glob
import csv
import argparse

#load kernel modules for 1-wire interface if it's not enabled already.
#os.system('modprobe w1-gpio')
#os.system('modprobe w1-therm')
 
base_dir = '/sys/bus/w1/devices/'

def find_sensors():

sensors = glob.glob(base_dir + '28*')
if not sensors:
    raise RuntimeError("No 1-Wire temperature sensor found.")

#device_folder = devices[0]
#device_file = device_folder + '/w1_slave'
#device_file1 = '/sys/bus/w1/devices/28-00000fee2cf2/w1_slave'
#device_file2 = '/sys/bus/w1/devices/28-00000fed00d3/w1_slave'

def read_temp_raw(device_file):
    with open(device_file, 'r') as f:
        return f.readlines()

def read_temp(device_file):
    lines = read_temp_raw(device_file)
    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw(device_file)
    pos = lines[1].find('t=')
    if pos != -1:
        temp = float(lines[1][pos+2:]) / 1000.0
        return temp

sensor_files = {os.path.basename(s): s + '/w1_slave' for s in sensors}

try:
    while True:
        for sensor_id, file in sensor_files.items():
            temp = read_temp(file)
            print(f"{sensor_id}: {temp:.2f} °C")
        print('-' * 30)
        time.sleep(1)
except KeyboardInterrupt:
    print("Terminated by user.")
