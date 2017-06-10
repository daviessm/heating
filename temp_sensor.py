import pygatt, pygatt.backends
import struct, time, logging
import dbus

from pygatt.exceptions import NotConnectedError, NotificationTimeout
from pygatt.backends.dbusbackend.dbusbackend import DBusBluetoothLEDevice

logger = logging.getLogger('heating')

class TempSensor(object):
  def __init__(self, dongle, mac):
    self.mac = mac
    self.dongle = dongle
    self.sent_alert = False
    self.amb_temp = None
    self.temp_job_id = None
    self.tag = DBusBluetoothLEDevice(self.mac, self.dongle)
    self.connect()

  def connect(self):
    self.tag.connect()

  def disconnect(self):
    self.tag.disconnect()

  def get_ambient_temp(self):
    pass

  @staticmethod
  def find_temp_sensors():
    dongle = pygatt.backends.DBusBackend(connect_timeout=40)
    logger.debug('Scanning for SensorTags')
    devices = dongle.scan(min_devices=1, device_name="(SensorTag|MetaWear)")
    sensors = {}
    for device in devices:
      if 'SensorTag' in device['name']:
        logger.info('Found SensorTag with address: ' + device['address'])
        sensors[device['address']] = SensorTag(dongle, device['address'])
      elif 'MetaWear' in device['name']:
        logger.info('Found MetaWear with address: ' + device['address'])
        sensors[device['address']] = MetaWear(dongle, device['address'])
    if len(sensors) == 0:
      dongle.stop()
      logger.exception('No sensors found!')
      raise Exception('No sensors found!')
    return sensors

class SensorTag(TempSensor):
  def __init__(self, dongle, mac):
    TempSensor.__init__(self, dongle, mac)

  def get_ambient_temp(self):
    self.connect()
    tAmb = 0
    failures = 0
    while tAmb == 0 and failures < 4:
      try:
        #Turn red LED on
        self.tag.char_write('f000aa65-0451-4000-b000-000000000000', bytearray([0x01]))
        self.tag.char_write('f000aa66-0451-4000-b000-000000000000', bytearray([0x01]))

        #Turn temperature sensor on
        self.tag.char_write('f000aa02-0451-4000-b000-000000000000', bytearray([0x01]))

        time.sleep(0.1)

        #Turn red LED off
        self.tag.char_write('f000aa65-0451-4000-b000-000000000000', bytearray([0x00]))
        self.tag.char_write('f000aa66-0451-4000-b000-000000000000', bytearray([0x00]))

        #Wait for reading
        count = 0
        while tAmb == 0 and count < 8:
          count += 1
          time.sleep(0.2)
          result = self.tag.char_read('f000aa01-0451-4000-b000-000000000000')
          (rawVobj, rawTamb) = struct.unpack('<hh', result)
          tAmb = rawTamb / 128.0

        #Turn temperature sensor off
        self.tag.char_write('f000aa02-0451-4000-b000-000000000000', bytearray([0x00]))
        if count == 8:
          failures += 1
        else:
          failures = 0

      except (NotConnectedError, NotificationTimeout) as nce1:
        try:
          logger.debug('nce1: ' + str(nce1))
          self.disconnect()
          self.connect()
          failures += 1
          time.sleep(1)
        except (NotConnectedError, NotificationTimeout) as nce2:
          logger.debug('nce2: ' + str(nce2))
          failures += 1
          time.sleep(1)
      #except DBusException as dbe:
      #  logger.debug('dbe: ' + str(dbe))
      #  self.failures += 1
      #  time.sleep(1)

    if tAmb == 0:
      self.amb_temp = None
      raise NoTemperatureException('Could not get temperature from ' + self.mac)
    logger.info('Got temperature ' + str(tAmb) + ' from ' + self.mac)
    self.amb_temp = tAmb

class MetaWear(TempSensor):
  def __init__(self, dongle, mac):
    TempSensor.__init__(self, dongle, mac)

  def get_ambient_temp(self):
    self.connect()
    tAmb = 0
    failures = 0
    while tAmb == 0 and failures < 4:
      try:
        #Turn red LED on
        self.tag.char_write('326a9001-85cb-9195-d9dd-464cfbbae75a', bytearray([0x02, 0x03, 0x01, 0x02, 0x1f, 0x1f, 0x00, 0x00, 0xd0, 0x07, 0x00, 0x00, 0xd0, 0x07, 0x00, 0x00, 0xff]))
        self.tag.char_write('326a9001-85cb-9195-d9dd-464cfbbae75a', bytearray([0x02, 0x01, 0x02]))

        #Turn temperature sensor on
        self.tag.char_write('326a9001-85cb-9195-d9dd-464cfbbae75a', bytearray([0x04, 0x81, 0x01]))

        time.sleep(0.1)

        #Turn red LED off
        self.tag.char_write('326a9001-85cb-9195-d9dd-464cfbbae75a', bytearray([0x02, 0x02, 0x01]))

        #Wait for reading
        count = 0
        while tAmb == 0 and count < 8:
          count += 1
          time.sleep(0.2)
          result = self.tag.char_read('326a9006-85cb-9195-d9dd-464cfbbae75a')
          (rawTamb,) = struct.unpack('<xxxh', str(result))
          tAmb = rawTamb / 8.0

        if count == 8:
          failures += 1
        else:
          failures = 0

      except (NotConnectedError, NotificationTimeout) as nce1:
        try:
          logger.debug('nce1: ' + str(nce1))
          self.disconnect()
          self.connect()
          failures += 1
          time.sleep(1)
        except (NotConnectedError, NotificationTimeout) as nce2:
          logger.debug('nce2: ' + str(nce2))
          failures += 1
          time.sleep(1)
      #except DBusException as dbe:
      #  logger.debug('dbe: ' + str(dbe))
      #  self.failures += 1
      #  time.sleep(1)

    if tAmb == 0:
      self.amb_temp = None
      raise NoTemperatureException('Could not get temperature from ' + self.mac)
    logger.info('Got temperature ' + str(tAmb) + ' from ' + self.mac)
    self.amb_temp = tAmb

class NoTagsFoundException(Exception):
  pass

class NoTemperatureException(Exception):
  pass

