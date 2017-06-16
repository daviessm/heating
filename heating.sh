#!/bin/bash
set -o xtrace
export HOME=/root
test_exit_code=1
while [ $test_exit_code -ne 3 ] ; do
  /etc/init.d/bluetooth stop
  rmmod -s -v bnep
  rmmod -s -v rfcomm
  rmmod -s -v btusb
  rmmod -s -v btrtl
  rmmod -s -v btbcm
  rmmod -s -v btintel
  sleep 2
  rmmod -s -v bluetooth
#  rm -r /var/lib/bluetooth/5C:F3:70:69:F9:F1
  rm -r /var/lib/bluetooth/5C:F3:70:75:D6:A1
  sleep 2
  modprobe btusb
  modprobe rfcomm
  /etc/init.d/bluetooth start
  hciconfig hci0 up
  sleep 1
  python2 heating.py
  test_exit_code=$?
done
