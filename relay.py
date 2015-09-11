import usb, logging

logger = logging.getLogger('heating')

class Relay(object):
  def __init__(self,device):
    #Assume relay is on until turned off
    self.status = 1

    self.hid_device = device
    if self.hid_device.is_kernel_driver_active(0):
      try:
        self.hid_device.detach_kernel_driver(0)
      except usb.core.USBError as e:
        raise Exception("Could not detatch kernel driver: %s" % str(e))
    try:
      self.hid_device.set_configuration()
      self.hid_device.reset()
    except usb.core.USBError as e:
      raise Exception("Could not set configuration: %s" % str(e))

    self.off()

  def __sendmsg(self,data):
    sentmsg = "".join(chr(n) for n in data)
    self.hid_device.ctrl_transfer(0x21,0x09,0x0300,0x00,sentmsg,1000)

  def on(self):
    if self.status == 0:
      logger.info("Relay ON")
      self.__sendmsg([0xFE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
      self.status = 1

  def off(self):
    if self.status == 1:
      logger.info("Relay OFF")
      self.__sendmsg([0xFC, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
      self.status = 0

  @staticmethod
  def find_relay():
    hid_devices = usb.core.find(find_all=True,idVendor=0x16c0,idProduct=0x05df)
    relays = []
    for hid_device in hid_devices:
      relays.append(Relay(hid_device))
    if len(relays) < 1:
      raise Exception("No relays found")
    if len(relays) > 1:
      raise Exception("Only one relay allowed!")
    
    return relays[0]

