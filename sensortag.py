import pygatt, pygatt.backends
import struct, time, logging
import dbus

from temp_sensor import TempSensor
from pygatt.exceptions import NotConnectedError, NotificationTimeout
from pygatt.backends.dbusbackend.dbusbackend import DBusBluetoothLEDevice

logger = logging.getLogger('heating')

class SensorTag(TempSensor):
  def __init__(self, dongle, mac):
    TempSensor.__init__(self, dongle, mac)

  def get_ambient_temp(self):
    tAmb = 0
    while tAmb == 0 and self.failures < 4:
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
          self.failures += 1

      except (NotConnectedError, NotificationTimeout) as nce1:
        try:
          logger.debug('nce1: ' + str(nce1))
          self.disconnect()
          self.connect()
          self.failures += 1
          time.sleep(1)
        except (NotConnectedError, NotificationTimeout) as nce2:
          logger.debug('nce2: ' + str(nce2))
          self.failures += 1
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

