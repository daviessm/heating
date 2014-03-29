#!/usr/bin/python
import os, sys, struct
 
import usb.core, usb.util
 
from time import sleep
import random

class Relay(object):
  def __init__(self,device):
    self.hid_device = device
    if self.hid_device.is_kernel_driver_active(0):
      try:
        self.hid_device.detach_kernel_driver(0)
      except usb.core.USBError as e:
        sys.exit("Could not detatch kernel driver: %s" % str(e))
    try:
      self.hid_device.set_configuration()
      self.hid_device.reset()
    except usb.core.USBError as e:
      sys.exit("Could not set configuration: %s" % str(e))

  def __sendmsg(self,data):
    sentmsg = "".join(chr(n) for n in data)
    self.hid_device.ctrl_transfer(0x21,0x09,0x0300,0x00,sentmsg,1000)

  def on(self):
    print "Relay ON"
    self.__sendmsg([0xFE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

  def off(self):
    print "Relay OFF"
    self.__sendmsg([0xFC, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

  @staticmethod
  def find_relays():
    hid_devices = usb.core.find(find_all=True,idVendor=0x16c0,idProduct=0x05df)
    relays = []
    for hid_device in hid_devices:
      relays.append(Relay(hid_device))

    return relays

class Temper(object):
  def __init__(self,device):
    self.hid_device = device
    if self.hid_device.is_kernel_driver_active(0):
      try:
        self.hid_device.detach_kernel_driver(0)
      except usb.core.USBError as e:
        pass
      try:
        self.hid_device.detach_kernel_driver(1)
      except usb.core.USBError as e:
        pass

    try:
      self.hid_device.set_configuration(1)
      self.hid_device.reset()
      usb.util.claim_interface(self.hid_device, 1)
    except usb.core.USBError as e:
      sys.exit("Could not set configuration: %s" % str(e))

  def __ctrl_transfer(self,wValue,wIndex,data):
    self.hid_device.ctrl_transfer(0x21,0x09,wValue,wIndex,data,1000)

  def __read(self):
    return self.hid_device.read(0x82,8,1,1000)

  def get_temperature(self):
    self.__ctrl_transfer(0x0201,0x00,"\x01\x01")
    self.__ctrl_transfer(0x0200,0x01,"\x01\x80\x33\x01\x00\x00\x00\x00") # ini_control_transfer
    self.__read()
    self.__ctrl_transfer(0x0200,0x01,"\x01\x82\x77\x01\x00\x00\x00\x00") # uIni1
    self.__read()
    self.__ctrl_transfer(0x0200,0x01,"\x01\x86\xff\x01\x00\x00\x00\x00") # uIni2
    self.__read()
    self.__read()
    self.__ctrl_transfer(0x0200,0x01,"\x01\x80\x33\x01\x00\x00\x00\x00") # uTemperatura
    data = self.__read()
    data_s = "".join([chr(byte) for byte in data])
    temp_c = 125.0/32000.0*(struct.unpack('>h', data_s[2:4])[0])
    return temp_c

  @staticmethod
  def find_tempers():
    hid_devices = usb.core.find(find_all=True,idVendor=0x0c45,idProduct=0x7401)
    tempers = []
    for hid_device in hid_devices:
      tempers.append(Temper(hid_device))

    return tempers


class Heating(object):
  def __init__(self):
    self.relays = Relay.find_relays()
    #if len(self.relays) < 1:
    #  raise Exception("No relays found")

    self.tempers = Temper.find_tempers()
    #if len(self.tempers) < 1:
    #  raise Exception("No tempers found")

    print "Self-test:"
    for r in self.relays:
      print "Relay %s" % r
      r.on()
      sleep(1)
      r.off()
    print "Finished relays"

    print ""
    for t in self.tempers:
      print "Temper %s" % t
      print t.get_temperature()
    print "Finished tempers"


if __name__ == '__main__':
  heating = Heating()

