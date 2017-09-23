import struct, time, logging, threading
import dbus

from bluepy.btle import Scanner, DefaultDelegate, Peripheral, BTLEException
from bluepy import btle

logger = logging.getLogger('heating')

class TempSensor(object):
  _scanning_lock = threading.Lock()

  def __init__(self, peripheral):
    self.mac = peripheral.addr
    self.sent_alert = False
    self.amb_temp = None
    self.temp_job_id = None
    self.peripheral = Peripheral(peripheral)
    self.characteristics = {}

  def connect(self):
    self.tag.connect()

  def disconnect(self):
    self.tag.disconnect()

  def get_ambient_temp(self):
    pass

  def _write_uuid(self, uuid, data):
    try:
      if not uuid in self.characteristics:
        self.characteristics[uuid] = self.peripheral.getCharacteristics(uuid=uuid)[0]

      #If there's still no characteristic, error
      if not uuid in self.characteristics:
        raise Exception('UUID ' + str(uuid) + ' not found on device ' + self.mac)

      self.characteristics[uuid].write(data)
    except BTLEException as e:
      logger.warn(self.mac + ' disconnected. Try to reconnect.')
      raise DisconnectedException(e.message)

  def _read_uuid(self, uuid):
    try:
      if not uuid in self.characteristics:
        self.characteristics[uuid] = self.peripheral.getCharacteristics(uuid=uuid)[0]

      #If there's still no characteristic, error
      if not uuid in self.characteristics:
        raise Exception('UUID ' + str(uuid) + ' not found on device ' + self.mac)

      return self.characteristics[uuid].read()
    except BTLEException as e:
      logger.warn(self.mac + ' disconnected. Try to reconnect.')
      raise DisconnectedException(e.message)

  @staticmethod
  def find_temp_sensors(sensors):
    TempSensor._scanning_lock.acquire()
    logger.debug('Scanning for devices')
    scanner = Scanner().withDelegate(ScanDelegate())
    try:
      devices = scanner.scan(10.0)
      if sensors is None:
        sensors = {}
      for device in devices:
        if device.addr in sensors:
          continue
        name = ''
        if device.getValueText(9):
          name = device.getValueText(9)
        elif device.getValueText(8):
          name = device.getValueText(8)
        logger.debug('Device name: ' + name)
        if 'SensorTag' in name:
          logger.info('Found SensorTag with address: ' + device.addr)
          sensors[device.addr] = SensorTag(device)
        elif 'MetaWear' in name:
          logger.info('Found MetaWear with address: ' + device.addr)
          sensors[device.addr] = MetaWear(device)
      logger.debug('Finished scanning for devices')
      TempSensor._scanning_lock.release()
      if len(sensors) == 0:
        raise NoTagsFoundException('No sensors found!')
    except BTLEException as e:
      scanner.stop()
      logger.warn('Got exception ' + e.message)
      TempSensor._scanning_lock.release()
    return sensors

class ScanDelegate(DefaultDelegate):
  def __init__(self):
    DefaultDelegate.__init__(self)

  def handleDiscovery(self, dev, isNewDev, isNewData):
    pass

class SensorTag(TempSensor):
  def __init__(self, peripheral):
    TempSensor.__init__(self, peripheral)

  def get_ambient_temp(self):
    tAmb = 0
    failures = 0
    while tAmb == 0 and failures < 4:
      try:
        #Turn red LED on
        self._write_uuid('f000aa65-0451-4000-b000-000000000000', b'\x01')
        self._write_uuid('f000aa66-0451-4000-b000-000000000000', b'\x01')

        #Turn temperature sensor on
        self._write_uuid('f000aa02-0451-4000-b000-000000000000', b'\x01')

        time.sleep(0.1)

        #Turn red LED off
        self._write_uuid('f000aa65-0451-4000-b000-000000000000', b'\x00')
        self._write_uuid('f000aa66-0451-4000-b000-000000000000', b'\x00')

        #Wait for reading
        count = 0
        while tAmb == 0 and count < 8:
          count += 1
          time.sleep(0.2)
          result = self._read_uuid('f000aa01-0451-4000-b000-000000000000')
          (rawVobj, rawTamb) = struct.unpack('<hh', result)
          tAmb = rawTamb / 128.0

        #Turn temperature sensor off
        self._write_uuid('f000aa02-0451-4000-b000-000000000000', b'\x00')
        if count == 8:
          failures += 1
        else:
          failures = 0

      except DisconnectedException as e:
        raise NoTemperatureException(e.message)

    if tAmb == 0:
      self.amb_temp = None
      raise NoTemperatureException('Could not get temperature from ' + self.mac)
    logger.info('Got temperature ' + str(tAmb) + ' from ' + self.mac)
    self.amb_temp = tAmb

class MetaWear(TempSensor):
  def __init__(self, peripheral):
    TempSensor.__init__(self, peripheral)

  def get_ambient_temp(self):
    self.connect()
    tAmb = 0
    failures = 0
    while tAmb == 0 and failures < 4:
      try:
        #Turn red LED on
        self._write_uuid('326a9001-85cb-9195-d9dd-464cfbbae75a', b'\x02\x03\x01\x02\x1f\x1f\x00\x00\xd0\x07\x00\x00\xd0\x07\x00\x00\xff')
        self._write_uuid('326a9001-85cb-9195-d9dd-464cfbbae75a', b'\x02\x01\x02')

        #Turn temperature sensor on
        self._write_uuid('326a9001-85cb-9195-d9dd-464cfbbae75a', b'\x04\x81\x01')

        time.sleep(0.1)

        #Turn red LED off
        self._write_uuid('326a9001-85cb-9195-d9dd-464cfbbae75a', b'\x02\x02\x01')

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

      except DisconnectedException as e:
        raise NoTemperatureException(e.message)

    if tAmb == 0:
      self.amb_temp = None
      raise NoTemperatureException('Could not get temperature from ' + self.mac)
    logger.info('Got temperature ' + str(tAmb) + ' from ' + self.mac)
    self.amb_temp = tAmb

class NoTagsFoundException(Exception):
  pass

class DisconnectedException(Exception):
  pass

class NoTemperatureException(Exception):
  pass

