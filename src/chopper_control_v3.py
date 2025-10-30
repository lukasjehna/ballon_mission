import RPi.GPIO as GPIO
import time
import argparse

#Constans
SERVO_PIN=12
PWM_FREQ=50
MIN_DUTY=2.5
MAX_DUTY=10.5

#Servo Control Setup
def init_servo(pin=SERVO_PIN, freq=PWM_FREQ);
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(servoPIN, GPIO.OUT)
    p = GPIO.PWM(servoPIN, 50) # GPIO 12 als PWM mit 50Hz
    pwd.start(0)
    return pwd  



parser= argparse.ArgumentParser(description="Insert angle between 0 and 180*")
parser.add_argument("PWM",type=float,nargs="?", default=90)
args=parser.parse_args()


def set_angle(angle):
    duty= min_duty + (angle / 180.0) * (max_duty-min_duty) 
    pwd.ChangeDutyCycle(duty)
    time.sleep(0.5)
    pwd.ChangeDutyCycle(0)  # stop sending signal to avoid jitter

set_angle(args.PWM)
pwd.stop()
GPIO.cleanup()
