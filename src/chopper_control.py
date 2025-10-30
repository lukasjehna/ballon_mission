import RPi.GPIO as GPIO
import time
import argparse

#Constans
SERVO_PIN=12
PWM_FREQ=50
MIN_DUTY=2.5
MAX_DUTY=10.5

#Servo Control Setup
def init_servo(pin=SERVO_PIN, freq=PWM_FREQ):
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.OUT)
    pwd = GPIO.PWM(pin, 50) # GPIO 12 als PWM mit 50Hz
    pwd.start(0)
    return pwd  

def set_angle(angle,pwd):
    duty= MIN_DUTY + (angle / 180.0) * (MAX_DUTY-MIN_DUTY) 
    pwd.ChangeDutyCycle(duty)
    time.sleep(0.5)
    pwd.ChangeDutyCycle(0)  # stop sending signal to avoid jitter

def main():
    parser= argparse.ArgumentParser(description="Set servo angle between 0 and 180°")
    parser.add_argument("angle",type=float,nargs="?", default=90)
    args=parser.parse_args()
    pwd=init_servo()
    try:
        set_angle(args.angle,pwd)
    finally:
        pwd.stop()
        GPIO.cleanup()

if __name__ == "__main__":
    main()
