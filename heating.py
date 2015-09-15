#!/usr/bin/python
import datetime, sys, threading, os, time, inspect, pytz, argparse, smtplib
import logging, logging.config, logging.handlers
from sensortag import SensorTag, NoTemperatureException
from relay import Relay
from httpserver import *

from dateutil import parser
from apiclient import discovery
from email.mime.text import MIMEText
from apscheduler.schedulers.background import BackgroundScheduler

import oauth2client
from oauth2client import client
from oauth2client import tools

UPDATE_CALENDAR_INTERVAL=900 #seconds
UPDATE_TEMPERATURE_INTERVAL=60 #seconds
PROPORTIONAL_HEATING_INTERVAL=30 # minutes
MINIMUM_TEMP=9
CALENDAR_ID='fkjecfkial36lojtvjlua77qio@group.calendar.google.com'
EMAIL_FROM='root@steev.me.uk'
EMAIL_TO=EMAIL_FROM
EMAIL_SERVER='localhost'
LOCAL_TIMEZONE=pytz.timezone('Europe/London')

logging.config.fileConfig('logging.conf')
logger = logging.getLogger('heating')


class Heating(object):
  def __init__(self):
    self.processing_lock = threading.Lock()
    self.calendar_lock = threading.Lock()
    self.temperature_lock = threading.Lock()
    self.relay_lock = threading.Lock()

    self.proportional_on_job = None
    self.proportional_off_job = None
    self.next_event_end_job = None
    #Sensible defaults
    self.next_event = None
    self.desired_temp = 20
    self.current_temp = [30]
    self.proportional_time = 0
    self.time_on = None
    self.time_off = None

  def start(self):
    logger.info('Starting')
    self.relay = Relay.find_relay()
    self.time_on = None
    self.time_off = None
    self.temp_sensors = SensorTag.find_sensortags()

    self.credentials = self.get_credentials()
    #Start getting events
    self.sched = BackgroundScheduler()
    self.sched.daemonic = False
    self.sched.start()

    self.start_threads()

  def on(self, proportion):
    self.time_on = pytz.utc.localize(datetime.datetime.utcnow())
    self.proportional_time = proportion
    self.relay_lock.acquire()
    self.relay.on()
    self.relay_lock.release()
    if self.proportional_on_job:
      self.proportional_on_job.remove()
      self.proportional_on_job = None
    if self.proportional_off_job:
      self.proportional_off_job.remove()
      self.proportional_off_job = None
    if proportion < PROPORTIONAL_HEATING_INTERVAL and self.time_on:
      run_date = self.time_on + datetime.timedelta(0,self.proportional_time * 60)
      self.proportional_off_job = self.sched.add_job(\
        self.process, trigger='date',\
        run_date=run_date, timezone=LOCAL_TIMEZONE,\
        name='Proportional off at ' + str(run_date.astimezone(LOCAL_TIMEZONE)))

  def off(self, proportion):
    self.time_off = pytz.utc.localize(datetime.datetime.utcnow())
    self.proportional_time = proportion
    self.relay_lock.acquire()
    self.relay.off()
    self.relay_lock.release()
    if self.proportional_on_job:
      self.proportional_on_job.remove()
      self.proportional_on_job = None
    if self.proportional_off_job:
      self.proportional_off_job.remove()
      self.proportional_off_job = None
    run_date = self.time_off + datetime.timedelta(0,PROPORTIONAL_HEATING_INTERVAL - self.proportional_time * 60)
    if proportion > 0:
      self.proportional_on_job = self.sched.add_job(\
        self.process, trigger='date',\
        run_date=run_date, timezone=LOCAL_TIMEZONE,\
        name='Proportional on at ' + str(run_date.astimezone(LOCAL_TIMEZONE)))

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
    self.temperature_lock.acquire()
    temps = []
    for mac, sensor in self.temp_sensors.iteritems():
      try:
        temps.append(sensor.get_ambient_temp())
      except NoTemperatureException as e:
        sensor.failures += 1
        logger.warn(str(e) + 'Retrying')
        if sensor.failures > 5 and not sensor.sent_alert:
          logger.error('Five failures getting temperature from ' + sensor.mac)
          #Send a warning email
          msg = MIMEText('Unable to reach SensorTag at ' + sensor.mac)
          msg['Subject'] = __name__
          msg['From'] = EMAIL_FROM
          msg['To'] = EMAIL_TO
          smtp = smtplib.SMTP(EMAIL_SERVER)
          smtp.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
          smtp.quit()
          sensor.sent_alert = True
      sensor.failures = 0
      sensor.alert_sent = False

    #self.current_temp = sum(temps) / float(len(temps))
    if len(temps) > 0: #Only update temperatures if we got something back
      self.current_temp = temps
    self.temperature_lock.release()

  def get_next_event(self):
    self.calendar_lock.acquire()
    http = self.credentials.authorize(httplib2.Http())
    service = discovery.build('calendar', 'v3', http=http)

    now = datetime.datetime.utcnow().isoformat() + 'Z'
    logger.debug('Getting the next event')
    eventsResult = service.events().list(
        calendarId=CALENDAR_ID, timeMin=now, maxResults=5, singleEvents=True, orderBy='startTime').execute()
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
        logger.info('Next event is ' + str(start_date.astimezone(LOCAL_TIMEZONE)) + \
          ' to ' + str(end_date.astimezone(LOCAL_TIMEZONE)) + ': ' + str(desired_temp) + ' degrees')
        self.next_event = (start_date, end_date, desired_temp)
        #Set a schedule to get the one after this
        if self.next_event_end_job:
          self.next_event_end_job.remove()
          self.next_event_end_job = None
        self.next_event_end_job = self.sched.add_job(self.get_next_event, \
          trigger='date', run_date=end_date, timezone=LOCAL_TIMEZONE, name='Event end at ' + str(end_date.astimezone(LOCAL_TIMEZONE)))
        break #Just need to get the first valid event
      except ValueError:
        logger.warn(event['summary'] + ' is not a number!')
    self.calendar_lock.release()

  def process(self):
    #Main calculations. Figure out whether the heating needs to be on or not.
    self.processing_lock.acquire()
    current_time =  pytz.utc.localize(datetime.datetime.utcnow())
    current_temp =  min(self.current_temp) # For the purposes of calculations use the minimum
    next_time =     self.next_event[0]
    next_time_end = self.next_event[1]
    next_temp =     self.next_event[2]
    temp_diff =     next_temp - current_temp

    if (not self.next_event) or \
        (self.next_event[0] > pytz.utc.localize(datetime.datetime.utcnow()) and \
         self.next_event[1] > pytz.utc.localize(datetime.datetime.utcnow())):
      self.desired_temp = str(MINIMUM_TEMP)
    else:
      self.desired_temp = str(next_temp)

    if current_temp < MINIMUM_TEMP:
      #If we're below the minimum allowed temperature, turn on at full blast.
      logger.info('Temperature is below minimum, turning on')
      self.on(PROPORTIONAL_HEATING_INTERVAL)

    elif not self.next_event:
      #If we don't have another event, return.
      logger.info('No next event available.')
      self.off(0)

    else:
      #Start half an hour earlier for each degree the heating is below the desired temp
      if next_time < current_time:
        time_due_on = next_time
        logger.info('Currently in an event starting at ' + str(next_time.astimezone(LOCAL_TIMEZONE)) + \
          ' ending at ' + str(next_time_end.astimezone(LOCAL_TIMEZONE)) + ' temp diff is ' + str(temp_diff))
      else:
        time_due_on = next_time - datetime.timedelta(0,temp_diff * 30 * 60)
        if time_due_on > next_time:
          time_due_on = next_time

        logger.info('Before an event starting at ' + str(next_time.astimezone(LOCAL_TIMEZONE)) +\
          ' temp diff is ' + str(temp_diff) + ' now due on at ' + str(time_due_on.astimezone(LOCAL_TIMEZONE)))

      if time_due_on <= current_time:
        if temp_diff < 0:
          #Is the current temperature higher than the next desired temperature?
          logger.info('Current temperature ' + str(current_temp) + ' is higher than the desired temperature ' + str(next_temp))
          self.off(0)
        else:
          #Calculate the proportional amount of time the heating needs to be on to reach the desired temperature
          new_proportional_time = temp_diff * PROPORTIONAL_HEATING_INTERVAL / 2
          if new_proportional_time < 10: #Minimum time boiler can be on to be worthwhile
            new_proportional_time = 10
          elif new_proportional_time > PROPORTIONAL_HEATING_INTERVAL:
            new_proportional_time = PROPORTIONAL_HEATING_INTERVAL
          if new_proportional_time != self.proportional_time:
            logger.info('New proportional time: ' + str(new_proportional_time) + ' minutes out of ' + str(PROPORTIONAL_HEATING_INTERVAL))

          #Are we currently on or off?
          if self.relay.status == 0: #Off
            if self.time_off:
              time_due_on = self.time_off + datetime.timedelta(0,(PROPORTIONAL_HEATING_INTERVAL * 60) - (self.proportional_time * 60))
              new_time_due_on = self.time_off + datetime.timedelta(0,(PROPORTIONAL_HEATING_INTERVAL * 60) - (new_proportional_time * 60))
            else:
              new_time_due_on = time_due_on

            if time_due_on != new_time_due_on:
              logger.info('Heating was off, due on at ' + str(time_due_on.astimezone(LOCAL_TIMEZONE)) +\
                           '. Now due on at ' + str(new_time_due_on.astimezone(LOCAL_TIMEZONE)))
            if new_time_due_on < current_time:
              self.on(new_proportional_time)
          else: #On
            if new_proportional_time < PROPORTIONAL_HEATING_INTERVAL:
              #Must have a time_on at this point
              time_due_off = self.time_on + datetime.timedelta(0,self.proportional_time * 60)
              new_time_due_off = self.time_on + datetime.timedelta(0,new_proportional_time * 60)
              if new_time_due_off < current_time:
                logger.info('Heating was on, due off at ' + str(time_due_off.astimezone(LOCAL_TIMEZONE)) +'. Turning off')
                self.off(new_proportional_time)
              else:
                if new_time_due_off != time_due_off:
                  logger.info('Heating was on, due off at ' + str(time_due_off.astimezone(LOCAL_TIMEZONE)) +\
                               '. Now due off at ' + str(new_time_due_off.astimezone(LOCAL_TIMEZONE)))
                self.proportional_time = new_proportional_time
            else:
              logger.info('Heating is on for maximum interval. Leaving on.')
      else:
        #Not due on
        logger.info('Not due on until ' + str(time_due_on.astimezone(LOCAL_TIMEZONE)))
        self.off(0)

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

def main():
  heating = Heating()
  try:
    heating.start()
  except Exception as e:
    logger.exception('Exception in main thread. Exiting.')
    heating.relay.off()
    sys.exit(1)

if __name__ == '__main__':
  main()

