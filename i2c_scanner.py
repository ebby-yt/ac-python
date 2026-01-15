import smbus
import time

bus = smbus.SMBus(1)  # Use I2C bus 1 (for Raspberry Pi 3+ and Zero)
for address in range(1, 128):
    try:
        bus.write_byte(address, 0)
        print(f"Device found at address: 0x{address:02X}")
    except:  # If there's no device at this address
        pass
