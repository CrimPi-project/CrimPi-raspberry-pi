import uasyncio as asyncio
import bluetooth
import random
import struct
import time
import machine
import ubinascii
from ble_advertising import advertising_payload
from micropython import const
from machine import Pin
from hx711 import HX711

DT = Pin(15, Pin.IN, pull=Pin.PULL_DOWN)  
SCK = Pin(16, Pin.OUT)
HX = HX711(SCK,DT)
OFFSET = -1
KG = 43679.05

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_GATTS_INDICATE_DONE = const(20)


_FLAG_READ = const(0x0002)
_FLAG_NOTIFY = const(0x0010)
_FLAG_INDICATE = const(0x0020)

_UART_SERVICE_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_TX = (
    bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"),
    _FLAG_NOTIFY,
)
_UART_RX = (
    bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"),
    bluetooth.FLAG_WRITE,
)

_UART_SERVICE = (
    _UART_SERVICE_UUID,
    (_UART_TX, _UART_RX),
)

# org.bluetooth.characteristic.gap.appearance.xml
_ADV_APPEARANCE_GENERIC_THERMOMETER = const(768)

class BLETemperature:
    def __init__(self, ble, name=""):
        self._ble = ble
        self.connected = False
        self._sending = False
        self.tare = False
        self.already_tared_in_workout = False
        self._ble.active(True)
        self._ble.irq(self._irq)
        ((self._tx_handle, self._rx_handle),) = self._ble.gatts_register_services((_UART_SERVICE,))
        self._connections = set()
        if len(name) == 0:
            name = 'Pico W'
        print('Sensor name %s' % name)
        self._payload = advertising_payload(
            name=name, services=[_UART_SERVICE_UUID]
        )
        self._advertise()

    def _irq(self, event, data):
        # Track connections so we can send notifications.
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, addr_type, addr_bytes = data
            self._connections.add(conn_handle)
            # Convert address bytes to a readable string for printing
            phone_address_str = ubinascii.hexlify(addr_bytes, ':').decode().upper()
            print(f"New connection from Central: {conn_handle}, Phone Address: {phone_address_str}")
            # Send the current temperature immediately upon connection
            self.connected = True
        elif event == _IRQ_GATTS_WRITE:
            conn_handle, attr_handle = data
            if attr_handle == self._rx_handle:
                cmd = self._ble.gatts_read(self._rx_handle).decode().strip().lower()
                print("Received command:", cmd)
                if cmd == "start":
                    if not self.already_tared_in_workout:
                        self.tare = True
                    self._sending = True
                elif cmd == "stop":
                    self._sending = False
        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, _, _ = data
            self._connections.remove(conn_handle)
            # Start advertising again to allow a new connection.
            self._advertise()
        elif event == _IRQ_GATTS_INDICATE_DONE:
            conn_handle, value_handle, status = data

    def update_temperature(self, notify=False, indicate=False):
        if self._connections:
            # Write the local value, ready for a central to read.
            weight = (HX.read()-OFFSET) / KG
            self._sensor_temp = weight # Corrected assignment to instance variable
            print("Weight: %.2f Kg" % weight);
            self._ble.gatts_write(self._tx_handle, struct.pack("<h", int(weight * 100)))
            if notify or indicate:
                for conn_handle in self._connections:
                    if notify:
                        # Notify connected centrals.
                        self._ble.gatts_notify(conn_handle,self._tx_handle)
                    if indicate:
                        # Indicate connected centrals.
                        self._ble.gatts_indicate(conn_handle,self._tx_handle)

    def _advertise(self, interval_us=500000):
        self._ble.gap_advertise(interval_us, adv_data=self._payload)

def demo():
    ble = bluetooth.BLE()
    temp = BLETemperature(ble)
    counter = 0
    led = Pin('LED', Pin.OUT)
    while True:
        if temp.tare:
            global OFFSET
            HX.tare()
            OFFSET = HX.read()
            temp.tare = False
            temp.already_tared_in_workout = True
            print('Tared:')
        if temp._sending:
            temp.update_temperature(notify=True, indicate=False)
            led.toggle()
        #else:
            #print('Waiting for command')
        time.sleep_ms(200)

if __name__ == "__main__":
    demo()

