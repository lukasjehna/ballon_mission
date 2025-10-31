import RPi.GPIO as GPIO #raspberry pi general purpose input/output
import time
import argparse

#Constans
SERVO_PIN=12
PWM_FREQ=50
MIN_DUTY=2.5
MAX_DUTY=10.5

def parse_arguments():
    parser= argparse.ArgumentParser(description="Set servo angle between 0 and 180°")
    parser.add_argument("angle",type=float,nargs="?", default=90)
    return parser.parse_args()
    
def init_servo(pin=SERVO_PIN, freq=PWM_FREQ):
    GPIO.setmode(GPIO.BCM) #Internal broadcom numbering instead of physical numbering from the board
    GPIO.setup(pin, GPIO.OUT) #define pin as out
    pwd = GPIO.PWM(pin, 50) # GPIO 12 als PWM mit 50Hz
    pwd.start(0) #0% duty cycle
    return pwd  

def set_angle(angle,pwd):
    duty= MIN_DUTY + (angle / 180.0) * (MAX_DUTY-MIN_DUTY) 
    pwd.ChangeDutyCycle(duty)
    time.sleep(0.5)
    pwd.ChangeDutyCycle(0)  # set duty cycle to 0

    
def main():
    args = parse_arguments()
    pwd=init_servo()
    try:
        set_angle(args.angle,pwd)
    finally:
        pwd.stop() #stops the signal completly
        GPIO.cleanup() #Resets pins to their default state.

if __name__ == "__main__":
    main()
