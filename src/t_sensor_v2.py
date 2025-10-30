# Complete Project Details: https://RandomNerdTutorials.com/raspberry-pi-ds18b20-python/

# Based on the Adafruit example: https://github.com/adafruit/Adafruit_Learning_System_Guides/blob/main/Raspberry_Pi_DS18B20_Temperature_Sensing/code.py
#added error handling
import os
import time
import glob

#load kernel modules for 1-wire interface if it's not enabled already.
#os.system('modprobe w1-gpio')
#os.system('modprobe w1-therm')
 
base_dir = '/sys/bus/w1/devices/'
devices = glob.glob(base_dir + '28*')
if not devices:
    raise RuntimeError("No 1-Wire temperature sensor found.")

device_folder = devices[0]
device_file = device_folder + '/w1_slave'
#device_file1 = '/sys/bus/w1/devices/28-00000fee2cf2/w1_slave'
#device_file2 = '/sys/bus/w1/devices/28-00000fed00d3/w1_slave'

def read_temp_raw():
    with open(device_file, 'r') as f:
        return f.readlines()

def read_temp():
    lines = read_temp_raw()
    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw()
    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        temp_string = lines[1][equals_pos+2:]
        temp_c = float(temp_string) / 1000.0
        return temp_c
    
try:
    while True:
        print(read_temp())
        time.sleep(1)
except KeyboardInterrupt:
    print("Terminated by user.")
