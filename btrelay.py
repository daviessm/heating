import logging
import time
from struct import *
from relay import Relay
from bluetooth import *

logger = logging.getLogger('heating')

class BTRelay(Relay):
  def __init__(self,mac,status):
    self._mac = mac
    self._status = status

    #Turn off at start
    if self._status == 1:
      time.sleep(2)
      self.off()

  def on(self):
    if self._status == 0:
      logger.info("Relay ON")
      sock = BluetoothSocket(RFCOMM)
      sock.connect((self._mac, 1))
      sock.send("\xAF\xFD\x00\xDF")
      sock.close()
      time.sleep(2)
      self._status = 1

  def off(self):
    if self._status == 1:
      logger.info("Relay OFF")
      sock = BluetoothSocket(RFCOMM)
      sock.connect((self._mac, 1))
      sock.send("\xAF\xFD\x01\xDF")
      sock.close()
      time.sleep(2)
      self._status = 0

  def status(self):
    try:
      logger.debug("Relay status")
      sock = BluetoothSocket(RFCOMM)
      sock.connect((self._mac, 1))
      sock.send("\xAF\xFD\x07\xDF")
      status = sock.recv(1024)
      sock.close()
      time.sleep(2)
      self._status = ord(status)
      return self._status
    except BluetoothError as e:
      raise

  @staticmethod
  def find_relay():
    try:
      devices = discover_devices(lookup_names=True)
      logger.debug("Found devices: " + str(devices))
      for (addr, name) in devices:
        if name == 'SPP-CA':
          sock = BluetoothSocket(RFCOMM)
          sock.connect((addr, 1))
          #Relay state
          sock.send("\xAF\xFD\x07\xDF")
          status = sock.recv(1024)
          sock.close()
          logger.info("Found relay with address " + addr + " and status " + str(ord(status)))
          relay = BTRelay(addr,ord(status))
          return relay
      return None
    except BluetoothError as e:
      raise
