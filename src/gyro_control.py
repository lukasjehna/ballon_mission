# !/usr/bin/python
import smbus
import math
import os
import time
import matplotlib.pyplot as plt

# Register
power_mgmt_1 = 0x6b
power_mgmt_2 = 0x6c

def read_byte(reg):
    return bus.read_byte_data(address, reg)

def read_word(reg):
    h = bus.read_byte_data(address, reg)
    l = bus.read_byte_data(address, reg+1)
    value = (h << 8) + l
    return value

def read_word_2c(reg):
    val = read_word(reg)
    if (val >= 0x8000):
        return -((65535 - val) + 1)
    else:
        return val

def dist(a,b):
    return math.sqrt((a*a)+(b*b))

def get_y_rotation(x,y,z):
    radians = math.atan2(x, dist(y,z))
    return -math.degrees(radians)

def get_x_rotation(x,y,z):
    radians = math.atan2(y, dist(x,z))
    return math.degrees(radians)

bus = smbus.SMBus(1)
address = 0x68       # via i2cdetect

# Start the bus to send request for data.
bus.write_byte_data(address, power_mgmt_1, 0)


while True:
        print("Gyroscope")
        print("--------")

        gyroscope_x = read_word_2c(0x43)/131
        gyroscope_y = read_word_2c(0x45)/131
        gyroscope_z = read_word_2c(0x47)/131

        print("gyroscope_x: ", gyroscope_x), 
        print("gyroscope_y: ", gyroscope_y), 
        print("gyroscope_z: ", gyroscope_z),

        print("Accelerometer")
        print("---------------------")

        acceleration_x = read_word_2c(0x3b)/16384
        acceleration_y = read_word_2c(0x3d)/16384
        acceleration_z = read_word_2c(0x3f)/16384


        print("acceleration_x:",acceleration_x)
        print("acceleration_y: ",acceleration_y) 
        print("acceleration_z: ",acceleration_z)

        print("X Rotation: " , get_x_rotation(acceleration_x, acceleration_y, acceleration_z))
        print("Y Rotation: " , get_y_rotation(acceleration_x, acceleration_y, acceleration_z))
        print("\n\n")
        #os.system('cls' if os.name == 'nt' else 'clear')
                
        time.sleep(2)
