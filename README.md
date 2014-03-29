heating
=======

Python project to control the central heating

I bought some temperature sensors ("TEMPer") and USB controlled relays off eBay with the goal of audomating my central heating system by switching it on and off as required based on a calendar and this software running on a single board computer (ODROID X/U/X2/U2/U3 / Paspberry Pi etc.).

The devices used are:

Temperature sensors
ID 0c45:7401 Microdia 

Relays
ID 16c0:05df Van Ooijen Technische Informatica HID device except mice, keyboards, and joysticks

Since there's so little code available for these devices on the internet, please feel free to use the control code provided here to write your own interfaces but the code is generally released under the GPLv3 and any major chunks of the code should be attributed to me.

The control code I have for the relay and the TEMPer were written by Patrick Jahns (patrick.jahns@gmail.com) and Philipp (https://github.com/padelt) respectively.

This project probably needs pyUSB v1.0.
