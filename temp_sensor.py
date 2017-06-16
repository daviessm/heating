import struct, time, logging
import dbus

from bluepy.btle import Scanner, DefaultDelegate, Peripheral
from bluepy import btle

logger = logging.getLogger('heating')

class TempSensor(object):
  def __init__(self, mac, addr_type):
    self.mac = mac
    self.sent_alert = False
    self.amb_temp = None
    self.temp_job_id = None
    self.peripheral = Peripheral(self.mac, addr_type)
    self.characteristics = {}

  def connect(self):
    self.tag.connect()

  def disconnect(self):
    self.tag.disconnect()

  def get_ambient_temp(self):
    pass

  def _write_uuid(self, uuid, data):
    if not uuid in self.characteristics:
      self.characteristics[uuid] = self.peripheral.getCharacteristics(uuid=uuid)[0]

    #If there's still no characteristic, error
    if not uuid in self.characteristics:
      raise Exception('UUID ' + str(uuid) + ' not found on device ' + self.mac)

    self.characteristics[uuid].write(data)

  def _read_uuid(self, uuid):
    if not uuid in self.characteristics:
      self.characteristics[uuid] = self.peripheral.getCharacteristics(uuid=uuid)[0]

    #If there's still no characteristic, error
    if not uuid in self.characteristics:
      raise Exception('UUID ' + str(uuid) + ' not found on device ' + self.mac)

    return self.characteristics[uuid].read()

  @staticmethod
  def find_temp_sensors():
    logger.debug('Scanning for devices')
    scanner = Scanner().withDelegate(ScanDelegate())
    devices = scanner.scan(10.0)
    sensors = {}
    for device in devices:
      name = ''
      if device.getValueText(9):
        name = device.getValueText(9)
      elif device.getValueText(8):
        name = device.getValueText(8)
      logger.debug('Device name: ' + name)
      if 'SensorTag' in name:
        logger.info('Found SensorTag with address: ' + device.addr)
        sensors[device.addr] = SensorTag(device.addr, device.addrType)
      elif 'MetaWear' in name:
        logger.info('Found MetaWear with address: ' + device.addr)
        sensors[device.addr] = MetaWear(device.addr, device.addrType)
    if len(sensors) == 0:
      raise Exception('No sensors found!')
    return sensors

class ScanDelegate(DefaultDelegate):
  def __init__(self):
    DefaultDelegate.__init__(self)

  def handleDiscovery(self, dev, isNewDev, isNewData):
    pass

class SensorTag(TempSensor):
  def __init__(self, mac, addr_type):
    TempSensor.__init__(self, mac, addr_type)

  def get_ambient_temp(self):
    tAmb = 0
    failures = 0
    while tAmb == 0 and failures < 4:
        #Turn red LED on
        self._write_uuid('f000aa65-0451-4000-b000-000000000000', '\x01')
        self._write_uuid('f000aa66-0451-4000-b000-000000000000', '\x01')

        #Turn temperature sensor on
        self._write_uuid('f000aa02-0451-4000-b000-000000000000', '\x01')

        time.sleep(0.1)

        #Turn red LED off
        self._write_uuid('f000aa65-0451-4000-b000-000000000000', '\x00')
        self._write_uuid('f000aa66-0451-4000-b000-000000000000', '\x00')

        #Wait for reading
        count = 0
        while tAmb == 0 and count < 8:
          count += 1
          time.sleep(0.2)
          result = self._read_uuid('f000aa01-0451-4000-b000-000000000000')
          (rawVobj, rawTamb) = struct.unpack('<hh', result)
          tAmb = rawTamb / 128.0

        #Turn temperature sensor off
        self._write_uuid('f000aa02-0451-4000-b000-000000000000', '\x00')
        if count == 8:
          failures += 1
        else:
          failures = 0

    if tAmb == 0:
      self.amb_temp = None
      raise NoTemperatureException('Could not get temperature from ' + self.mac)
    logger.info('Got temperature ' + str(tAmb) + ' from ' + self.mac)
    self.amb_temp = tAmb

class MetaWear(TempSensor):
  def __init__(self, mac, addr_type):
    TempSensor.__init__(self, mac, addr_type)

  def get_ambient_temp(self):
    self.connect()
    tAmb = 0
    failures = 0
    while tAmb == 0 and failures < 4:
      #Turn red LED on
      self._write_uuid('326a9001-85cb-9195-d9dd-464cfbbae75a', '\x02\x03\x01\x02\x1f\x1f\x00\x00\xd0\x07\x00\x00\xd0\x07\x00\x00\xff')
      self._write_uuid('326a9001-85cb-9195-d9dd-464cfbbae75a', '\x02\x01\x02')

      #Turn temperature sensor on
      self._write_uuid('326a9001-85cb-9195-d9dd-464cfbbae75a', '\x04\x81\x01')

      time.sleep(0.1)

      #Turn red LED off
      self._write_uuid('326a9001-85cb-9195-d9dd-464cfbbae75a', '\x02\x02\x01')

      #Wait for reading
      count = 0
      while tAmb == 0 and count < 8:
        count += 1
        time.sleep(0.2)
        result = self._read_uuid('326a9006-85cb-9195-d9dd-464cfbbae75a')
        (rawTamb,) = struct.unpack('<xxxh', str(result))
        tAmb = rawTamb / 8.0

      if count == 8:
        failures += 1
      else:
        failures = 0

    if tAmb == 0:
      self.amb_temp = None
      raise NoTemperatureException('Could not get temperature from ' + self.mac)
    logger.info('Got temperature ' + str(tAmb) + ' from ' + self.mac)
    self.amb_temp = tAmb

class NoTagsFoundException(Exception):
  pass

class NoTemperatureException(Exception):
  pass

