import pygatt, struct, time, logging

logger = logging.getLogger('heating')

class SensorTag(object):
  def __init__(self, dongle, mac):
    self.mac = mac
    self.dongle = dongle
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
    except pygatt.exceptions.NotConnectedError as e:
      self.connect()
      raise NoTemperatureException('Unable to read temperature')

    (rawVobj, rawTamb) = struct.unpack('<hh', result)
    tAmb = rawTamb / 128.0
    logger.debug('Got temperature ' + str(tAmb))
    return tAmb

  @staticmethod
  def find_sensortag():
    dongle = pygatt.backends.GATTToolBackend()
    logger.debug('Scanning for SensorTags')
    devices = dongle.scan()
    for device in devices:
      if device['name'] == 'CC2650':
        logger.info('Found SensorTag with address: ' + device['address'])
        return SensorTag(dongle, device['address'])
    raise Exception('No SensorTags found!')

class NoTemperatureException(Exception):
  pass

