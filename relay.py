import usb, logging

logger = logging.getLogger('heating')

class Relay(object):
  def __init__(self,device):
    #Assume relay is on until turned off
    self.status = [1,1,1,1,1,1,1,1]

  def all_status(self):
    pass

  def one_status(self,relay_num):
    pass

  def all_on(self):
    pass

  def all_off(self):
    pass

  def one_on(self,relay_num):
    pass

  def one_off(self,relay_num):
    pass

  @staticmethod
  def find_relay():
    pass

