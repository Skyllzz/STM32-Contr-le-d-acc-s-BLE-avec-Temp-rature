import time
import dht
import pyb
import bluetooth
from ble_advertising import advertising_payload
from micropython import const


dht_pin = pyb.Pin('A1', pyb.Pin.OPEN_DRAIN)
capteur = dht.DHT22(dht_pin)

buzzer = pyb.Pin('D5', pyb.Pin.OUT_PP)
buzzer.low()

servo_pin = pyb.Pin('D6')
timer = pyb.Timer(1, freq=50)
pwm_servo = timer.channel(1, pyb.Timer.PWM, pin=servo_pin)

def set_servo_angle(angle):
    if -90 <= angle <= 90:
        pw_percent = 3 + (angle + 90) * (12.5 - 3) / 180
        pwm_servo.pulse_width_percent(pw_percent)
        print("Servo angle :", angle)

set_servo_angle(0)

SIG = pyb.Pin('D7', pyb.Pin.OUT_PP)

def get_distance():
    try:
        SIG.init(pyb.Pin.OUT_PP)
        SIG.low()
        time.sleep_us(2)
        SIG.high()
        time.sleep_us(10)
        SIG.low()

        SIG.init(pyb.Pin.IN)
        start = time.ticks_us()
        while SIG.value() == 0:
            start = time.ticks_us()
        while SIG.value() == 1:
            end = time.ticks_us()

        duration = end - start
        return (duration * 0.0343) / 2
    except:
        return -1

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

_SERVICE_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_SENSOR_CHAR_UUID = bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E")
_CONTROL_CHAR_UUID = bluetooth.UUID("6E400004-B5A3-F393-E0A9-E50E24DCCA9E")

_FLAG_READ = const(0x0002)
_FLAG_NOTIFY = const(0x0010)
_FLAG_WRITE = const(0x0008)

class BLEServer:
    def __init__(self):
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self._irq)
        self._conn_handle = None
        self._manual_control = False
        self._servo_angle = 0
        self._last_manual_time = time.ticks_ms()

        ((self._sensor_handle, self._control_handle),) = self.ble.gatts_register_services(( 
            (_SERVICE_UUID, (
                (_SENSOR_CHAR_UUID, _FLAG_READ | _FLAG_NOTIFY),
                (_CONTROL_CHAR_UUID, _FLAG_WRITE),
            )),
        ))

        self.advertise()

    def advertise(self):
        payload = advertising_payload(name="NucleoBLE")
        self.ble.gap_advertise(100, adv_data=payload)
        print("BLE advertising...")

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self._conn_handle, _, _ = data
            print("BLE client connected")
        elif event == _IRQ_CENTRAL_DISCONNECT:
            print("BLE client disconnected")
            self._conn_handle = None
            self.advertise()
        elif event == _IRQ_GATTS_WRITE:
            conn_handle, value_handle = data
            if value_handle == self._control_handle:
                value = self.ble.gatts_read(self._control_handle)
                print("Commande recue :", value)

                self._manual_control = True
                self._last_manual_time = time.ticks_ms()

                if value.startswith(b'1'):
                    if self._servo_angle != 90:
                        set_servo_angle(90)
                        self._servo_angle = 90
                        print("Servo ouvert")
                    else:
                        print("Deja ouvert")
                elif value.startswith(b'0'):
                    if self._servo_angle != 0:
                        set_servo_angle(0)
                        self._servo_angle = 0
                        print("Servo ferme")
                    else:
                        print("Deja ferme")

    def send_data(self, data):
        if self._conn_handle is not None:
            self.ble.gatts_write(self._sensor_handle, data)
            self.ble.gatts_notify(self._conn_handle, self._sensor_handle)
            print("Donnees envoyees :", data)
        else:
            print("Aucun client BLE connecte")

server = BLEServer()

try:
    while True:
        try:
            capteur.measure()
            temp = capteur.temperature()
            hum = capteur.humidity()
            dist = get_distance()

            print("=========================")
            print("Temperature : {:.1f} C".format(temp))
            print("Humidite    : {:.1f} %".format(hum))
            print("Distance    : {:.1f} cm".format(dist))
            if temp > 30:
                print("Attention : temperature elevee !")
            print("=========================")

            buzzer.high() if temp > 30 else buzzer.low()

            if server._manual_control:
                if time.ticks_diff(time.ticks_ms(), server._last_manual_time) > 3000:
                    print("Retour au mode automatique")
                    server._manual_control = False

            if not server._manual_control:
                if 0 < dist < 15 and server._servo_angle != 90:
                    set_servo_angle(90)
                    server._servo_angle = 90
                elif dist >= 15 and server._servo_angle != 0:
                    set_servo_angle(0)
                    server._servo_angle = 0

            payload = "T:{:.1f}C H:{:.1f}%".format(temp, hum)
            server.send_data(payload)

        except Exception as e:
            print("Erreur capteurs :", e)

        time.sleep(1)

except KeyboardInterrupt:
    print("Programme arrete")
    buzzer.low()
    set_servo_angle(0)
