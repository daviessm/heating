#!/usr/bin/python
import datetime, sys, threading, httplib2, os, syslog, time, inspect, pytz, urlparse, logging, logging.handlers, argparse
from sensortag import SensorTag
from relay import Relay

from dateutil import parser
from apiclient import discovery
from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from SocketServer import ThreadingMixIn

import oauth2client
from oauth2client import client
from oauth2client import tools

UPDATE_CALENDAR_INTERVAL=60 #seconds
UPDATE_TEMPERATURE_INTERVAL=60 #seconds
PROPORTIONAL_HEATING_INTERVAL=30 # minutes
MINIMUM_TEMP=9

logger = logging.getLogger('heating')
logger.setLevel(logging.DEBUG)

syslog = logging.handlers.SysLogHandler(address='/dev/log',facility='local0')
syslog.setLevel(logging.DEBUG)
stdout = logging.StreamHandler(sys.stdout)
stdout.setLevel(logging.DEBUG)
stderr = logging.StreamHandler(sys.stderr)
stderr.setLevel(logging.ERROR)

syslog_formatter = logging.Formatter('%(filename)s@%(lineno)s %(msg)s')
console_formatter = logging.Formatter('%(asctime)s %(levelname)s %(filename)s@%(lineno)s %(msg)s')

syslog.setFormatter(syslog_formatter)
stdout.setFormatter(console_formatter)
stderr.setFormatter(console_formatter)

logger.addHandler(syslog)
logger.addHandler(stdout)
logger.addHandler(stderr)

class Heating(object):
  def __init__(self):
    logger.info('starting')
    self.processing_lock=threading.Lock()
    #Sensible defaults
    self.next_event = None
    self.current_temp = 30.0
    self.proportional_time = 0
    self.time_on = None
    self.time_off = None

    self.relay = Relay.find_relay()
    self.time_off = pytz.utc.localize(datetime.datetime.utcnow())
    self.temp_sensor = SensorTag.find_sensortag()
    
    self.credentials = self.get_credentials()
    #Start getting events
    self.start_threads()

  def on(self, proportion):
    self.time_on = pytz.utc.localize(datetime.datetime.utcnow())
    self.proportional_time = proportion
    self.relay.on()

  def off(self, proportion):
    self.time_off = pytz.utc.localize(datetime.datetime.utcnow())
    self.proportional_time = proportion
    self.relay.off()

  def start_threads(self):
    temperature_thread = threading.Thread(target = self.temperature_timer)
    temperature_thread.daemon = True
    temperature_thread.start()

    calendar_thread = threading.Thread(target = self.calendar_timer)
    calendar_thread.daemon = True
    calendar_thread.start()

    #Start HTTP server
    HttpHandler.heating = self
    server = ThreadedHTTPServer(('localhost', 8080), HttpHandler)
    server.serve_forever()

  def temperature_timer(self):
    while(True):
      self.get_temperature()
      self.process()
      time.sleep(UPDATE_TEMPERATURE_INTERVAL)

  def calendar_timer(self):
    while(True):
      self.get_next_event()
      self.process()
      time.sleep(UPDATE_CALENDAR_INTERVAL)

  def get_temperature(self):
    failures = 0
    try:
      self.current_temp = self.temp_sensor.get_ambient_temp()
      logger.debug('New temperature is ' + str(self.current_temp))
      failures = 0
    except NoTemperatureException as e:
      failures += 1
      logger.warn('No temperature reading! Retrying')
      if failures > 5:
        logger.error('Five failures gettimg temperature. Dying.')
        raise e

  def get_next_event(self):
    http = self.credentials.authorize(httplib2.Http())
    service = discovery.build('calendar', 'v3', http=http)
    
    now = datetime.datetime.utcnow().isoformat() + 'Z'
    logger.debug('Getting the next event')
    eventsResult = service.events().list(
        calendarId='fkjecfkial36lojtvjlua77qio@group.calendar.google.com', timeMin=now, maxResults=5, singleEvents=True, orderBy='startTime').execute()
    events = eventsResult.get('items', [])

    if not events:
      logger.info('No upcoming events found.')
    for event in events:
      start = event['start'].get('dateTime', event['start'].get('date'))
      start_date = parser.parse(start)
      end = event['end'].get('dateTime', event['end'].get('date'))
      end_date = parser.parse(end)
      try:
        desired_temp = float(event['summary'])
	logger.debug('Next event is ' + start + ' to ' + end + ': ' + str(desired_temp) + ' degrees')
        self.next_event = (start_date, end_date, desired_temp)
        break #Just need to get the first valid event
      except ValueError:
        logger.warn(event['summary'] + ' is not a number!')

  def process(self):
    #Main calculations. Figure out whether the heating needs to be on or not.
    self.processing_lock.acquire()
    current_time = pytz.utc.localize(datetime.datetime.utcnow())

    if self.current_temp < MINIMUM_TEMP:
      #If we're below the minimum allowed temperature, turn on.
      logger.debug('Temperature is below minimum, turning on')
      self.on(PROPORTIONAL_HEATING_INTERVAL)

    elif not self.next_event:
      #If we don't have another event, return.
      logger.debug('No next event available.')
      self.off(0)

    elif ((self.next_event[0] - current_time).seconds) + ((self.next_event[0] - current_time).days*24*60*60) > 60*60*3:
      #If next event begins more than three hours in the future, ignore it.
      logger.debug('Next event is more than three hours in the future: %s' % (str(self.next_event[0])))
      self.off(0)

    elif self.current_temp > self.next_event[2]:
      #Ok, so there's a possibility we might need to turn on.
      #Is the current temperature higher than the next desired temperature?
      logger.debug('Current temperature ' + str(self.current_temp) + ' is higher than the desired temperature ' + str(self.next_event[2]))
      self.off(0)

    else:
      #Calculate the proportional amount of time the heating needs to be on to reach the desired temperature
      temp_diff = self.next_event[2] - self.current_temp

      new_proportional_time = temp_diff * PROPORTIONAL_HEATING_INTERVAL / 2
      if new_proportional_time < 10: #Minimum time boiler can be on to be worthwhile
        new_proportional_time = 10
      elif new_proportional_time > PROPORTIONAL_HEATING_INTERVAL:
        new_proportional_time = PROPORTIONAL_HEATING_INTERVAL
      logger.debug('New proportional time: ' + str(new_proportional_time) + ' minutes out of ' + str(PROPORTIONAL_HEATING_INTERVAL))

      #Start half an hour earlier for each degree the heating is below the desired temp
      if ((self.next_event[0] - current_time).seconds) + ((self.next_event[0] - current_time).days*24*60*60) < 60*60*3 \
           and ((self.next_event[0] - current_time).seconds) + ((self.next_event[0] - current_time).days*24*60*60) > 0:
        time_due_on = self.next_event[0] - datetime.timedelta(0,temp_diff * 30 * 60)
        logger.debug('Initial warm-up, temp difference is ' + str(temp_diff) + '; next event is at ' + str(time_due_on))
        if time_due_on < current_time:
          self.on(new_propotional_time)
      else:
        if self.proportional_time == 0:
          logger.debug('Heating is off, turning on')
          self.on(new_proportional_time)
        else:
          logger.debug('Heating is proportional, shorten or lengthen the time interval as required')
          #Are we currently on or off?
          if self.relay.status == 0: #Off
            time_due_on = self.time_off + datetime.timedelta(0,(PROPORTIONAL_HEATING_INTERVAL * 60) - (self.proportional_time * 60))
            new_time_due_on = self.time_off + datetime.timedelta(0,(PROPORTIONAL_HEATING_INTERVAL * 60) - (new_proportional_time * 60))
            logger.debug('Heating was off, due on at ' + str(time_due_on) +'. Now due on at ' + str(new_time_due_on))
            if new_time_due_on < current_time:
              self.on(new_proportional_time)
          else: #On  
            time_due_off = self.time_on + datetime.timedelta(0,self.proportional_time * 60)
            new_time_due_off = self.time_on + datetime.timedelta(0,new_proportional_time * 60)
            logger.debug('Heating was on, due off at ' + str(time_due_off) +'. Now due off at ' + str(new_time_due_off))
            if new_time_due_off < current_time:
              self.off(new_proportional_time)

    logger.debug('Releasing processing lock')
    self.processing_lock.release()     

  def get_credentials(self):
    '''Gets valid user credentials from storage.

    If nothing has been stored, or if the stored credentials are invalid,
    the OAuth2 flow is completed to obtain the new credentials.

    Returns:
        Credentials, the obtained credential.
    '''
    home_dir = os.path.expanduser('~')
    credential_dir = os.path.join(home_dir, '.credentials')
    if not os.path.exists(credential_dir):
      os.makedirs(credential_dir)
    credential_path = os.path.join(credential_dir, 'calendar-heating.json')

    store = oauth2client.file.Storage(credential_path)
    credentials = store.get()
    parser = argparse.ArgumentParser(parents=[tools.argparser])
    flags = parser.parse_args()
    if not credentials or credentials.invalid:
      flow = client.flow_from_clientsecrets('client_secret.json', 'https://www.googleapis.com/auth/calendar.readonly')
      flow.user_agent = 'Heating'
      credentials = tools.run_flow(flow, store, flags)
      logger.info('Storing credentials to ' + credential_path)
    return credentials

class HttpHandler(BaseHTTPRequestHandler):
  heating = None

  def do_GET(self):
    parsed_path = urlparse.urlparse(self.path)
    if parsed_path.path == '/current_temp':
      logger.debug('Web request for /current_temp')
      self.send_response(200)
      self.end_headers()
      self.wfile.write(str(self.heating.current_temp) + '\n')
    elif parsed_path.path == '/desired_temp':
      logger.debug('Web request for /desired_temp')
      self.send_response(200)
      self.end_headers()
      if not self.next_event:
        self.wfile.write(str(MINIMUM_TEMP))
      else:
        self.wfile.write(str(self.next_event[2]))
    elif parsed_path.path == '/proportion':
      logger.debug('Web request for /proportion')
      self.send_response(200)
      self.end_headers()
      self.wfile.write(str(self.heating.proportional_time) + '\n')
    else:
      self.send_error(404)
    return

  def log_message(self, format, *args):
    return

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
  '''Handle requests in a separate thread.'''

class NoTemperatureException(Exception):
  pass

if __name__ == '__main__':
  heating = Heating()
  while True:
    time.sleep(1)
