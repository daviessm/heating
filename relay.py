import usb, logging

logger = logging.getLogger('heating')

class Relay(object):
  def __init__(self,device):
    #Assume relay is on until turned off
    self.status = 0

  def on(self):
    pass

  def off(self):
    pass

  @staticmethod
  def find_relay():
    pass

