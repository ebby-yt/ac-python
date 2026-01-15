import time
import board
import neopixel

# LED strip configuration
pixel_pin = board.D18  # GPIO 15 is referred to as D14 in the library
num_pixels = 55
brightness = 1.0

# Create the NeoPixel object
pixels = neopixel.NeoPixel(pixel_pin, num_pixels, brightness=brightness, auto_write=False)

# Set all pixels to red
pixels.fill((255, 0, 0))
pixels.show()
time.sleep(2)

# Turn off the pixels
pixels.fill((0, 0, 0))
pixels.show()
