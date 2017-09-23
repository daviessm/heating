import usb, logging
from relay import Relay

logger = logging.getLogger('heating')

class SingleRelay():
  def __init__(self,device):
    #Assume relay is on until turned off
    self._status = True

    self._hid_device = device
    if self._hid_device.is_kernel_driver_active(0):
      try:
        self._hid_device.detach_kernel_driver(0)
      except usb.core.USBError as e:
        raise Exception("Could not detatch kernel driver: %s" % str(e))
    try:
      self._hid_device.set_configuration()
      self._hid_device.reset()
    except usb.core.USBError as e:
      raise Exception("Could not set configuration: %s" % str(e))

    #Turn off at start
    self.off()

  def __sendmsg(self,data):
    self._hid_device.ctrl_transfer(0x21,0x09,0x0300,0x00,bytes(data),1000)

  def on(self):
    self.__sendmsg([0xFE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    logger.info("Relay " + str(self._hid_device.address) + " on")
    self._status = True

  def off(self):
    self.__sendmsg([0xFC, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    logger.info("Relay " + str(self._hid_device.address) + " off")
    self._status = False

  @property
  def port_numbers(self):
    return self._hid_device.port_numbers

class USBMultipleRelays(Relay):
  def __init__(self,relays):
    self._relays = relays

  def all_status(self):
    status = []
    cnt = 0
    for relay in self._relays:
      if relay._status:
        status.append(1)
      else:
        status.append(0)
      cnt += 1
    return status

  def one_status(self,relay_num):
    if self._relays[relay_num-1]._status:
      return 1
    else:
      return 0

  def all_on(self):
    logger.debug("Relays all on")
    for relay in self._relays:
      relay.on()

  def all_off(self):
    logger.debug("Relays all off")
    for relay in self._relays:
      relay.off()

  def one_on(self,relay_num):
    status = self.all_status()
    if status[relay_num-1] == 0 and relay_num > 0 and relay_num <= 8:
      logger.debug("Relay " + str(relay_num) + " on")
      relay = self._relays[relay_num-1]
      relay.on()

  def one_off(self,relay_num):
    status = self.all_status()
    if status[relay_num-1] == 1 and relay_num > 0 and relay_num <= 8:
      logger.debug("Relay " + str(relay_num) + " off")
      relay = self._relays[relay_num-1]
      relay.off()

  @staticmethod
  def find_relays():
    hid_devices = usb.core.find(find_all=True,idVendor=0x16c0,idProduct=0x05df)
    relays = []
    for hid_device in hid_devices:
      relays.append(SingleRelay(hid_device))
    if len(relays) < 1:
      raise Exception("No relays found")

    return USBMultipleRelays(relays)
