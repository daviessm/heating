import logging
import time
from struct import *
from relay import Relay
from bluetooth import *

logger = logging.getLogger('heating')

class BTRelay(Relay):
  def __init__(self,mac,status):
    self.__mac = mac
    self.__status = status

    #Turn off at start
    if self.__status == 1:
      time.sleep(2)
      self.off()

  def on(self):
    if self.__status == 0:
      logger.info("Relay ON")
      sock = BluetoothSocket(RFCOMM)
      sock.connect((self.__mac, 1))
      sock.send("\xAF\xFD\x00\xDF")
      sock.close()
      time.sleep(2)
      self.__status = 1

  def off(self):
    if self.__status == 1:
      logger.info("Relay OFF")
      sock = BluetoothSocket(RFCOMM)
      sock.connect((self.__mac, 1))
      sock.send("\xAF\xFD\x01\xDF")
      sock.close()
      time.sleep(2)
      self.__status = 0

  def status(self):
    try:
      logger.debug("Relay status")
      sock = BluetoothSocket(RFCOMM)
      sock.connect((self.__mac, 1))
      sock.send("\xAF\xFD\x07\xDF")
      status = sock.recv(1024)
      sock.close()
      time.sleep(2)
      return ord(status)
    except BluetoothError as e:
      raise

  @staticmethod
  def find_relay():
    try:
      devices = discover_devices(lookup_names=True)
      for (addr, name) in devices:
        if name == 'SPP-CA':
          sock = BluetoothSocket(RFCOMM)
          sock.connect((addr, 1))
          #Relay state
          sock.send("\xAF\xFD\x07\xDF")
          status = sock.recv(1024)
          print ord(status)
          sock.close()
          logger.info("Found relay with address " + addr + " and status " + str(ord(status)))
          relay = BTRelay(addr,ord(status))
          return relay
      return None
    except BluetoothError as e:
      raise
