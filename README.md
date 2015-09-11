heating
=======

Python project to control the central heating based on a calendar, a wireless temperature sensor and this software running on a single board computer (ODROID X/U/X2/U2/U3 / Paspberry Pi etc.).

The devices used are:

Relay
ID 16c0:05df Van Ooijen Technische Informatica HID device except mice, keyboards, and joysticks

SensorTag
Texas Instruments CC2650STK

Plugable USB Bluetooth/LE dongle using btusb driver
0a5c:21e8

Since there's so little code available for these devices on the internet, please feel free to use the control code provided here to write your own interfaces but the code is generally released under the GPLv3 and any major chunks of the code should be attributed to me. 

The control code I have for the relay was written by Patrick Jahns (patrick.jahns@gmail.com; https://github.com/patrickjahns/simpleusbrelay) and is released under the MIT license as described on his Github.

This project probably needs pyUSB v1.0b4 and a load of other things.


