import usb, logging
from relay import Relay

logger = logging.getLogger('heating')

class USBRelay(Relay):
  def __init__(self,device):
    #Assume relay is on until turned off
    self._status = [1,1,1,1,1,1,1,1]

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
    self.all_off()

  def __sendmsg(self,data):
    command = "".join(chr(n) for n in data)
    self._hid_device.ctrl_transfer(0x21,0x09,0x0300,0x00,command,1000)

  def all_status(self):
    return self._status

  def one_status(self,relay_num):
    return self._status[relay_num-1]

  def all_on(self):
    if not self._status == [1,1,1,1,1,1,1,1]:
      logger.debug("Relay all on")
      self.__sendmsg([0xFE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
      self._status = [1,1,1,1,1,1,1,1]

  def all_off(self):
    if not self._status == [0,0,0,0,0,0,0,0]:
      logger.debug("Relay all off")
      self.__sendmsg([0xFC, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
      self._status = [0,0,0,0,0,0,0,0]

  def one_on(self,relay_num):
    if self._status[relay_num-1] == 0 and relay_num > 0 and relay_num <= 8:
      logger.debug("Relay " + str(relay_num) + " on")
      self.__sendmsg([0xFF, relay_num, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
      self._status[relay_num-1] = 1

  def one_off(self,relay_num):
    if self._status[relay_num-1] == 1 and relay_num > 0 and relay_num <= 8:
      logger.debug("Relay " + str(relay_num) + " off")
      self.__sendmsg([0xFD, relay_num, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
      self._status[relay_num-1] = 0

  @staticmethod
  def find_relay():
    hid_devices = usb.core.find(find_all=True,idVendor=0x16c0,idProduct=0x05df)
    relays = []
    for hid_device in hid_devices:
      relays.append(USBRelay(hid_device))
    if len(relays) < 1:
      raise Exception("No relays found")
    if len(relays) > 1:
      raise Exception("Only one relay allowed!")

    return relays[0]
