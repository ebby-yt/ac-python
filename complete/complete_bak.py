import os
import glob
import time
import max30102
import hrcalc
from rpi_ws281x import *
import argparse
import smbus

# KS0023 initalization
os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')
base_dir = '/sys/bus/w1/devices/'
device_folder = glob.glob(base_dir + '28*')[0]
device_file = device_folder + '/w1_slave'

# LED output initialization
LED_COUNT      = 144
LED_PIN        = 18
LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
LED_DMA        = 10      # DMA channel to use for generating a signal (try 10)
LED_BRIGHTNESS = 65      # Set to 0 for darkest and 255 for brightest
LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)
LED_CHANNEL    = 0       # set to '1' for GPIOs 13, 19, 41, 45 or 53

# MIN/MAX values initalization
TEMP_MIN = 0
TEMP_MAX = 40

SPO2_MIN = 90
SPO2_MAX = 100

RYTH_MIN = 50
RYTH_MAX = 110

def read_temp_raw():
    f = open(device_file, 'r')
    lines = f.readlines()
    f.close()
    return lines

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

def colorWipe(strip, color, wait_ms=50):
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, color)
        strip.show()
        time.sleep(wait_ms/1000.0)

def clean_data(raw_r, raw_g, raw_b, clean_r, clean_g, clean_b):
    if raw_r < RYTH_MIN :
        raw_r = RYTH_MIN
    elif raw_r > RYTH_MAX :
        raw_r = RYTH_MAX
    clean_r = int((raw_r - RYTH_MIN) * (255 / (RYTH_MAX - RYTH_MIN)))

    if raw_g != 0 :
        if raw_g < SPO2_MIN :
            raw_g = SPO2_MIN
        elif raw_g > SPO2_MAX :
            raw_g = SPO2_MAX
        clean_g = int((raw_g - SPO2_MIN) * (255 / (SPO2_MAX - SPO2_MIN)))

    if raw_b != 0 :
        if raw_b < TEMP_MIN :
            raw_b = TEMP_MIN
        elif raw_b > TEMP_MAX :
            raw_b = TEMP_MAX
        clean_b = int((raw_b - TEMP_MIN) * (255 / (TEMP_MAX - TEMP_MIN)))

    return clean_r, clean_g, clean_b

if __name__ == '__main__' :
    # MAX30102 initialization
    m = max30102.MAX30102()
    # LED strip initialization
    strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
    # Intialize the library (must be called once before other functions).
    strip.begin()
    raw_r, raw_g, raw_b = 0, 0, 0
    color_r, color_b, color_g = 0, 0, 0
    try:
        while True:
            print("Reading temp")
            raw_b = read_temp()
            print("SPO2 and HR")
            m = None
            m = max30102.MAX30102()
            time.sleep(0.5)
            print("Reading sequential data")
            # Read data from the sensor
            red, ir = m.read_sequential()
            # Calculate heart rate and SpO2
            print("Calculating HR & SPO2")
            hr, hr_valid, spo2, spo2_valid = hrcalc.calc_hr_and_spo2(ir, red)
#            m.reset()
#            m.setup()
            # Check if valid readings are obtained
            if hr_valid :
                raw_r = hr
            if spo2_valid :
                raw_g = spo2
            #if hr_valid and spo2_valid:
            #    raw_r = hr
            #    raw_g = spo2
            #else:
            #    print("Invalid readings. Please try again.")

            # Clean raw data
            print("Cleaning data")
            color_r, color_g, color_b = clean_data(raw_r, raw_g, raw_b, color_r, color_g, color_b)
            print((color_r, color_g, color_b))

            # Fill the strip with new colors
            print("Displaying")
            colorWipe(strip, Color(color_r, color_g, color_b))
            #print("R : " + {color_r} + " G : " + {color_g} + " B : " + {color_b})
            #print(color_r)
            #print(color_g)
            #print(color_b)
            time.sleep(0.5)
    except KeyboardInterrupt:
        # Clear the strip
        colorWipe(strip, Color(0, 0, 0))
