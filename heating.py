#!/usr/bin/python
import datetime, sys, struct, threading, usb, httplib2, os, syslog, time, inspect, pytz, urlparse

from dateutil import parser
from apiclient import discovery
from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from SocketServer import ThreadingMixIn

import oauth2client
from oauth2client import client
from oauth2client import tools

UPDATE_CALENDAR_INTERVAL=30 #seconds
UPDATE_TEMPERATURE_INTERVAL=60 #seconds

syslog.openlog(logoption=syslog.LOG_PID, facility=syslog.LOG_LOCAL1)

def get_trace_prefix():
  return inspect.stack()[2][3] + '@' + str(inspect.stack()[2][2]) + ': '

def DEBUG(text):
  output_msg = get_trace_prefix() + text
  syslog.syslog(syslog.LOG_DEBUG, output_msg)
  print "Debug " + output_msg

def INFO(text):
  output_msg = get_trace_prefix() + text
  syslog.syslog(syslog.LOG_INFO, output_msg)
  print "Info " + output_msg

def WARN(text):
  output_msg = get_trace_prefix() + text
  syslog.syslog(syslog.LOG_WARN, output_msg)
  print "Warn " + output_msg

def ERROR(text):
  output_msg = get_trace_prefix() + text
  syslog.syslog(syslog.log_ERROR, output_msg)
  print "Error " + output_msg

class Relay(object):
  def __init__(self,device):
    #Assume relay is on until turned off
    self.status = 1

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

    self.off()

  def __sendmsg(self,data):
    sentmsg = "".join(chr(n) for n in data)
    self.hid_device.ctrl_transfer(0x21,0x09,0x0300,0x00,sentmsg,1000)

  def on(self):
    if self.status == 0:
      INFO("Relay ON")
      self.__sendmsg([0xFE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
      self.status = 1

  def off(self):
    if self.status == 1:
      INFO("Relay OFF")
      self.__sendmsg([0xFC, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
      self.status = 0

  @staticmethod
  def find_relay():
    hid_devices = usb.core.find(find_all=True,idVendor=0x16c0,idProduct=0x05df)
    relays = []
    for hid_device in hid_devices:
      relays.append(Relay(hid_device))
    if len(relays) < 1:
      ERROR("No relays found")
      raise Exception("No relays found")
    if len(relays) > 1:
      ERROR("Only one relay allowed!")
      raise Exception("Only one relay allowed!")
    
    return relays[0]

class Heating(object):
  def __init__(self):
    #Sensible defaults
    self.next_event = None
    self.current_temp = 30

    self.relay = Relay.find_relay()
    #self.temp_sensor = SensorTag.find_sensor()
    
    self.credentials = self.get_credentials()
    #Start getting events
    self.start_threads()

  def start_threads(self):
    temperature_thread = threading.Thread(target = self.temperature_timer)
    temperature_thread.daemon = True
    temperature_thread.start()

    calendar_thread = threading.Thread(target = self.calendar_timer)
    calendar_thread.daemon = True
    calendar_thread.start()

    processing_thread = threading.Thread(target = self.processing_timer)
    processing_thread.daemon = True
    processing_thread.start()

    #Start HTTP server
    HttpHandler.heating = self
    server = ThreadedHTTPServer(('localhost', 8080), HttpHandler)
    server.serve_forever()

  def temperature_timer(self):
    while(True):
      self.get_temperature()
      time.sleep(UPDATE_TEMPERATURE_INTERVAL)

  def calendar_timer(self):
    while(True):
      self.get_next_event()
      time.sleep(UPDATE_CALENDAR_INTERVAL)

  def processing_timer(self):
    while(True):
      self.process()
      #time.sleep(UPDATE_TEMPERATURE_INTERVAL)
      time.sleep(15)

  def get_temperature(self):
    DEBUG("Getting default temperature of 30")
    self.current_temperature = 30

  def get_next_event(self):
    http = self.credentials.authorize(httplib2.Http())
    service = discovery.build('calendar', 'v3', http=http)
    
    now = datetime.datetime.utcnow().isoformat() + 'Z'
    DEBUG('Getting the next event')
    eventsResult = service.events().list(
        calendarId='fkjecfkial36lojtvjlua77qio@group.calendar.google.com', timeMin=now, maxResults=5, singleEvents=True, orderBy='startTime').execute()
    events = eventsResult.get('items', [])

    if not events:
      INFO('No upcoming events found.')
    for event in events:
      start = event['start'].get('dateTime', event['start'].get('date'))
      start_date = parser.parse(start)
      end = event['end'].get('dateTime', event['end'].get('date'))
      end_date = parser.parse(end)
      try:
        desired_temp = float(event['summary'])
	DEBUG('Next event is ' + start + ' to ' + end + ': ' + str(desired_temp) + ' degrees')
        self.next_event = (start_date, end_date, desired_temp)
        break #Just need to get the first valid event
      except ValueError:
        WARN(event['summary'] + ' is not a number!')

  def process(self):
    #Main calculations. Figure out whether the heating needs to be on or not.

    #If we don't have another event, return.
    if not self.next_event:
      DEBUG("No next event available.")
      self.relay.off()
      return

    current_time = pytz.utc.localize(datetime.datetime.utcnow())
    #If next event begins more than three hours in the future, ignore it.
    if ((self.next_event[0] - current_time).seconds) + ((self.next_event[0] - current_time).days*24*60*60) > 60*60*3:
      DEBUG("Next event is more than three hours in the future: %s and %s" % (str(self.next_event[0]), str(pytz.utc.localize(datetime.datetime.utcnow()))))
      self.relay.off()
      return

    #Ok, so there's a possibility we might need to turn on.
    #Is the current temperature higher than the next desired temperature?
    if self.current_temp > self.next_event[2]:
      DEBUG("Current temperature is higher than the desired temperature.")
      self.relay.off()
      return

    #Now, work out whether the heating needs to be on.
    #If there's a temperature set now, and we're 2 or more degrees below it, turn on.
    if ((self.next_event[0] - current_time).seconds) + ((self.next_event[0] - current_time).days*24*60*60) < 0 and self.current_temp + 2 < self.next_event[2]:
      self.relay.on()
      return

  def get_credentials(self):
    """Gets valid user credentials from storage.

    If nothing has been stored, or if the stored credentials are invalid,
    the OAuth2 flow is completed to obtain the new credentials.

    Returns:
        Credentials, the obtained credential.
    """
    home_dir = os.path.expanduser('~')
    credential_dir = os.path.join(home_dir, '.credentials')
    if not os.path.exists(credential_dir):
        os.makedirs(credential_dir)
    credential_path = os.path.join(credential_dir,
                                   'calendar-heating.json')

    store = oauth2client.file.Storage(credential_path)
    credentials = store.get()
    if not credentials or credentials.invalid:
        flow = client.flow_from_clientsecrets('client_secret.json', 'https://www.googleapis.com/auth/calendar.readonly')
        flow.user_agent = 'Heating'
        credentials = tools.run_flow(flow, store, flags)
        INFO('Storing credentials to ' + credential_path)
    return credentials

  def self_test(self):
    INFO("Self-test:")
    for r in self.relays:
      INFO("Relay %s" % r)
      r.on()
      sleep(1)
      r.off()
    DEBUG("Finished relays")

    print ""
    for t in self.tempers:
      INFO("Temper %s at %d" % t, t.get_temperature())
    DEBUG("Finished tempers")

class HttpHandler(BaseHTTPRequestHandler):
  heating = None

  def do_GET(self):
    parsed_path = urlparse.urlparse(self.path)
    if parsed_path.path == "/temp":
      DEBUG("Web request, sending response " + str(self.heating.current_temp))
      self.send_response(200)
      self.end_headers()
      self.wfile.write(str(self.heating.current_temp) + "\n")
    else:
      self.send_error(404)
    return

  def log_message(self, format, *args):
    return

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
  """Handle requests in a separate thread."""


if __name__ == '__main__':
  heating = Heating()
  while True:
    time.sleep(1)
