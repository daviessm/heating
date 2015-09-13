import pygatt, struct, time, logging

from pygatt.exceptions import NotConnectedError

logger = logging.getLogger('heating')

class SensorTag(object):
  def __init__(self, dongle, mac):
    self.mac = mac
    self.dongle = dongle
    self.failures = 0
    self.sent_alert = False
    self.amb_temp = 30
    self.connect()

  def connect(self):
    self.tag = pygatt.BluetoothLEDevice(self.mac, self.dongle)
    self.tag.connect()

  def disconnect(self):
    self.tag.stop()

  def get_ambient_temp(self):
    try:
      #Turn red LED on
      self.tag.char_write_handle(0x4e, bytearray([0x01]))
      self.tag.char_write_handle(0x50, bytearray([0x01]))

      #Turn temperature sensor on
      self.tag.char_write_handle(0x24, bytearray([0x01]))

      #Wait for reading
      time.sleep(0.3)
      result = self.tag.char_read_handle(0x21)

      #Turn temperature sensor off
      self.tag.char_write_handle(0x24, bytearray([0x00]))

      #Turn red LED off
      self.tag.char_write_handle(0x4e, bytearray([0x00]))
      self.tag.char_write_handle(0x50, bytearray([0x00]))
    except pygatt.exceptions.NotConnectedError as nce1:
      try:
        self.connect()
      except NotConnectedError as nce2:
        self.failures += 1
      raise NoTemperatureException('Unable to read temperature from ' + self.mac)

    (rawVobj, rawTamb) = struct.unpack('<hh', result)
    tAmb = rawTamb / 128.0
    logger.info('Got temperature ' + str(tAmb) + ' from ' + self.mac)
    self.amb_temp = tAmb
    return self.amb_temp

  @staticmethod
  def find_sensortags():
    dongle = pygatt.backends.GATTToolBackend()
    logger.debug('Scanning for SensorTags')
    devices = dongle.scan()
    sensortags = {}
    for device in devices:
      if device['name'] == 'CC2650':
        logger.info('Found SensorTag with address: ' + device['address'])
        sensortags[device['address']] = SensorTag(pygatt.backends.GATTToolBackend(), device['address'])
    if len(sensortags) == 0:
      raise Exception('No SensorTags found!')
    dongle.stop()
    return sensortags

class NoTemperatureException(Exception):
  pass

