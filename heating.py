#!/usr/bin/python
import datetime, sys, threading, os, time, inspect, pytz, argparse, smtplib, uuid
import logging, logging.config, logging.handlers
from temp_sensor import TempSensor, NoTemperatureException, NoTagsFoundException
from relay import Relay
from btrelay import BTRelay
from usbrelay import USBRelay
from httpserver import *

from dateutil import parser
from apiclient import discovery
from apiclient.errors import HttpError
from email.mime.text import MIMEText
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.events import *

import oauth2client
from oauth2client import client
from oauth2client import tools

from bluepy import btle

UPDATE_CALENDAR_INTERVAL=6 #hours
UPDATE_TEMPERATURE_INTERVAL=60 #seconds
PROPORTIONAL_HEATING_INTERVAL=20 # minutes
MIN_ACTIVE_PERIOD=8
EFFECT_DELAY=20 #minutes
MINS_PER_DEGREE=25 #minutes
MINIMUM_TEMP=9
CALENDAR_ID='fkjecfkial36lojtvjlua77qio@group.calendar.google.com'
CALENDAR_TIMEOUT=30 #seconds
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
    self.relay_lock = threading.Lock()

    self.heating_trigger = None
    self.preheat_trigger = None
    self.event_trigger = None
    #Sensible defaults
    self.events = None
    self.desired_temp = MINIMUM_TEMP
    self.current_temp = None
    self.proportional_time = 0
    self.time_on = None
    self.time_off = None
    self.event_sync_id = None
    self.relay = None
    self.http_server = None
    self.temp_sensors = None
    self.sched = None

  def start(self):
    logger.info('Starting')
    self.credentials = self.get_credentials()

    logger.debug('Searching for SensorTags')
    self.temp_sensors = TempSensor.find_temp_sensors()
    logger.debug('Searching for relay')
    #self.relay = BTRelay.find_relay()
    self.relay = USBRelay.find_relay()

    logger.debug('Setting up scheduler and error handler')
    self.sched = BlockingScheduler()
    self.sched.add_listener(self.scheduler_listener, EVENT_JOB_ERROR)

    #Get a new temperature every minute
    logger.debug('Creating scheduler jobs')
    for mac, sensor in self.temp_sensors.iteritems():
      sensor.temp_job_id = self.sched.add_job(self.get_temperature, trigger = 'cron', \
        next_run_time = pytz.utc.localize(datetime.datetime.utcnow()), args = (sensor,), second = 0)

    #Get new events every X minutes
    self.sched.add_job(self.get_next_event, trigger = 'cron', \
        next_run_time = pytz.utc.localize(datetime.datetime.utcnow()), hour = '*/' + str(UPDATE_CALENDAR_INTERVAL), minute = 0)

    HttpHandler.heating = self
    logger.debug('Starting HTTP server')
    self.http_server = ThreadedHTTPServer(('localhost', 8080), HttpHandler)
    http_server_thread = threading.Thread(target=self.http_server.serve_forever)
    http_server_thread.setDaemon(True) # don't hang on exit
    http_server_thread.start()

    logger.debug('Starting scheduler')
    try:
      self.sched.start()
    except Exception as e:
      logger.error('Error in scheduler: ' + str(e))
      for mac, sensor in self.temp_sensors.iteritems():
        try:
          sensor.tag._backend.stop()
        except Exception as e1:
          pass
      self.http_server.shutdown()
      self.sched.shutdown(wait = False)

  def scheduler_listener(self, event):
    pass
    #if event.exception is not None:
    #  logger.error('Error in scheduled event: ' + str(event))
    #  logger.debug(type(event.exception))
    #  if not isinstance(event.exception, NoTemperatureException):
    #    logger.error('Killing all the things')
    #    for mac, sensor in self.temp_sensors.iteritems():
    #      try:
    #        sensor.tag._backend.stop()
    #      except Exception as e1:
    #        pass
    #    self.http_server.shutdown()
    #    self.sched.shutdown(wait = False)

  def heating_on(self, proportion):
    self.time_on = pytz.utc.localize(datetime.datetime.utcnow())
    self.time_off = None
    self.proportional_time = proportion
    self.relay_lock.acquire()
    self.relay.one_on(1)
    self.relay_lock.release()
    self.set_heating_trigger(proportion, 1)

  def heating_off(self, proportion):
    self.time_off = pytz.utc.localize(datetime.datetime.utcnow())
    self.time_on = None
    self.relay_lock.acquire()
    self.relay.one_off(1)
    self.relay_lock.release()
    self.set_heating_trigger(proportion, 0)

  def preheat_on(self, time_off):
    logger.info('Preheat on')
    self.relay_lock.acquire()
    self.relay.one_on(2)
    self.relay_lock.release()
    self.set_preheat_trigger(time_off)

  def preheat_off(self):
    logger.info("Preheat off")
    self.relay_lock.acquire()
    self.relay.one_off(2)
    self.relay_lock.release()

  def check_relay_states(self):
    logger.debug('Checking states ' + str(self.relay.all_status()))
    iter = 0
    for s in self.relay.all_status():
      iter += 1
      if s == 0:
        self.relay.one_off(iter)
      else:
        self.relay.one_on(iter)

  def set_heating_trigger(self, proportion, on):
    self.proportional_time = proportion
    if self.heating_trigger is not None:
      self.heating_trigger.remove()
      self.heating_trigger = None
    if on == 0:
      if proportion > 0:
        if self.time_off is None:
          self.time_off = pytz.utc.localize(datetime.datetime.utcnow())
        run_date = self.time_off + datetime.timedelta(0,(PROPORTIONAL_HEATING_INTERVAL - self.proportional_time) * 60)
        logger.info('New proportional time: ' + str(proportion) + '/' + str(PROPORTIONAL_HEATING_INTERVAL) +\
          ' mins - will turn on at ' + str(run_date.astimezone(LOCAL_TIMEZONE)))
        self.heating_trigger = self.sched.add_job(\
          self.process, trigger='date', run_date=run_date, name='Proportional on at ' + str(run_date.astimezone(LOCAL_TIMEZONE)))
    else:
      if proportion < PROPORTIONAL_HEATING_INTERVAL:
        run_date = self.time_on + datetime.timedelta(0,self.proportional_time * 60)
        logger.info('New proportional time: ' + str(proportion) + '/' + str(PROPORTIONAL_HEATING_INTERVAL) +\
          ' mins - will turn off at ' + str(run_date.astimezone(LOCAL_TIMEZONE)))
        self.heating_trigger = self.sched.add_job(\
          self.process, trigger='date', run_date=run_date, name='Proportional off at ' + str(run_date.astimezone(LOCAL_TIMEZONE)))

  def set_preheat_trigger(self, time_off):
    if self.preheat_trigger is not None:
      self.preheat_trigger.remove()
      self.preheat_trigger = None
    logger.info('Preheat off at ' + str(time_off.astimezone(LOCAL_TIMEZONE)))
    self.preheat_trigger = self.sched.add_job(\
      self.preheat_off, trigger='date', run_date=time_off, name='Preheat off at ' + str(time_off.astimezone(LOCAL_TIMEZONE)))


  def get_temperature(self, sensor):
    try:
      sensor.get_ambient_temp()
    except NoTemperatureException as e:
      logger.warn(str(e) + ' - Retrying')
      if sensor.failures >= 5 and not sensor.sent_alert:
        logger.error('Five failures getting temperature from ' + sensor.mac)
        #Send a warning email
        msg = MIMEText('Unable to reach SensorTag at ' + sensor.mac)
        msg['Subject'] = 'Heating: Failure getting temperature reading'
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        smtp = smtplib.SMTP(EMAIL_SERVER)
        smtp.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
        smtp.quit()
        sensor.sent_alert = True
    sensor.failures = 0
    sensor.alert_sent = False

    self.update_current_temp()

  def update_current_temp(self):
    temps = []
    for mac, sensor in self.temp_sensors.iteritems():
      if sensor.amb_temp is not None:
        temps.append(sensor.amb_temp)

    if not temps:
      raise NoTemperatureException('No temperatures.')
    #self.current_temp = sum(temps) / float(len(temps))
    self.current_temp = min(temps)
    logger.info('Overall temperature is now ' + str(self.current_temp) + ' from ' + str(temps))

    self.process()

  def get_next_event(self):
    self.calendar_lock.acquire()
    http = self.credentials.authorize(httplib2.Http(timeout=CALENDAR_TIMEOUT))
    service = discovery.build('calendar', 'v3', http=http)

    now = datetime.datetime.utcnow().isoformat() + 'Z'
    logger.debug('Getting the next event')
    try:
      eventsResult = service.events().list(
        calendarId=CALENDAR_ID, timeMin=now, maxResults=3, singleEvents=True, orderBy='startTime').execute()
      events = eventsResult.get('items', [])
      self.event_sync_id = str(uuid.uuid4())
      logger.debug('Sending request: ' + str({'id':self.event_sync_id, \
              'type':'web_hook', \
              'address':'https://www.steev.me.uk/heating/events', \
              'expiration':(int(time.time())+(UPDATE_CALENDAR_INTERVAL*60*60))*1000 \
             }))
      hook_response = service.events().watch(calendarId=CALENDAR_ID, \
        body={'id':self.event_sync_id, \
              'type':'web_hook', \
              'address':'https://www.steev.me.uk/heating/events', \
              'expiration':(int(time.time())+(UPDATE_CALENDAR_INTERVAL*60*60))*1000 \
             })\
        .execute()
      if hook_response is not None:
        logger.debug('Got response' + str(hook_response) + ' from web_hook call')
    except HttpError as e:
      logger.error('HttpError, resp = ' + str(e.resp) + '; content = ' + str(e.content))
      logger.exception(e)
      self.calendar_lock.release()
      return
    except Exception as e:
      logger.exception(e)
      self.calendar_lock.release()
      return

    parsed_events = []
    if events:
      counter = 0
      for event in events:
        counter += 1
        start = event['start'].get('dateTime', event['start'].get('date'))
        start_date = parser.parse(start)
        end = event['end'].get('dateTime', event['end'].get('date'))
        end_date = parser.parse(end)

        try:
          desired_temp = float(event['summary'])
        except ValueError:
          if event['summary'].lower() == 'on':
            desired_temp = 'On'
          if event['summary'].lower() == 'preheat':
            desired_temp = 'Preheat'

        logger.info('Event ' + str(counter) + ' is ' + str(start_date.astimezone(LOCAL_TIMEZONE)) + \
          ' to ' + str(end_date.astimezone(LOCAL_TIMEZONE)) + ': ' + str(desired_temp))
        parsed_events.append({'start_date': start_date, 'end_date': end_date, 'desired_temp': desired_temp})
        if counter == 1:
          #Set a schedule to get the one after this
          if self.event_trigger is not None:
            self.event_trigger.remove()
            self.event_trigger = None

          self.event_trigger = self.sched.add_job(self.get_next_event, \
            trigger='date', run_date=end_date, name='Event end at ' + str(end_date.astimezone(LOCAL_TIMEZONE)))

          #Tell the processing that this is a new event so it resets the proportion to start again
          if self.events is None or start_date != self.events[0]['start_date'] or end_date != self.events[0]['end_date'] or desired_temp != self.events[0]['desired_temp']:
            logger.info('New event starting, resetting time off.')
            self.time_off = None

      self.events = parsed_events

    self.calendar_lock.release()
    self.process()

  def process(self):
    #Main calculations. Figure out whether the heating needs to be on or not.
    if self.current_temp is None:
      return

    self.processing_lock.acquire()

    current_time = pytz.utc.localize(datetime.datetime.utcnow())
    current_temp = self.current_temp
    time_due_on  = None
    have_temp_event = False
    forced_on = False

    if self.events is not None:
      #Find preheat events
      index = -1
      while index < 3:
        index += 1

        if index >= len(self.events):
          break

        have_preheat = False
        if self.events[index]['desired_temp'] == 'Preheat':
          if self.events[index]['start_date'] < current_time and not self.events[index]['end_date'] < current_time:
            have_preheat = True
            if self.relay.one_status(2) == 0:
              self.preheat_on(self.events[index]['end_date'])
            break

        if (not have_preheat) and self.relay.one_status(2) == 1:
          self.preheat_off()

      #Find normal events
      index = -1
      next_time = None

      while index < 3:
        index += 1

        if index >= len(self.events):
          break

        if self.events[index]['desired_temp'] == 'Preheat':
          continue
        elif self.events[index]['desired_temp'] == 'On':
          if self.events[index]['start_date'] < current_time and not self.events[index]['end_date'] < current_time:
            forced_on = True
            if self.relay.one_status(1) == 0:
              logger.info('Heating forced on')
              self.heating_on(PROPORTIONAL_HEATING_INTERVAL)
        else:
          have_temp_event = True
          break

        next_time =     self.events[index]['start_date']
        next_time_end = self.events[index]['end_date']
        next_temp =     self.events[index]['desired_temp']

        if self.events is None or \
            (next_time     > pytz.utc.localize(datetime.datetime.utcnow()) and \
             next_time_end > pytz.utc.localize(datetime.datetime.utcnow())) or \
            (not have_temp_event and not forced_on):
          self.desired_temp = str(MINIMUM_TEMP)

      if current_temp < MINIMUM_TEMP:
        #If we're below the minimum allowed temperature, turn on at full blast.
        logger.info('Temperature is below minimum, turning on')
        self.heating_on(PROPORTIONAL_HEATING_INTERVAL)

      elif self.events is None or (not have_temp_event and not forced_on):
        #If we don't have an event yet, warn and ensure relay is off
        logger.warn('No next event available.')
        self.heating_off(0)

      else:
        logger.debug('Processing data: ' + str(next_time.astimezone(LOCAL_TIMEZONE)) + \
          ' to ' + str(next_time_end.astimezone(LOCAL_TIMEZONE)) + ', ' + str(next_temp))

        self.desired_temp = str(next_temp)

        if next_time_end < current_time:
          #If the last event ended in the past, off.
          logger.warn('Event end time is in the past.')
          self.heating_off(0)

        elif not forced_on:
          temp_diff = next_temp - current_temp
          new_proportional_time = None
          if next_time < current_time:
            time_due_on = next_time
            logger.info('Currently in an event starting at ' + str(next_time.astimezone(LOCAL_TIMEZONE)) + \
              ' ending at ' + str(next_time_end.astimezone(LOCAL_TIMEZONE)) + ' temp diff is ' + str(temp_diff))

          #Check all events for warm-up temperature
          for event in self.events:
            if event['desired_temp'] == 'On' or event['desired_temp'] == 'Preheat':
              continue

            event_next_time = event['start_date']
            if event_next_time > current_time:
              event_desired_temp = event['desired_temp']
              event_temp_diff = event_desired_temp - current_temp
              logger.debug('Future event starting at ' + str(event_next_time.astimezone(LOCAL_TIMEZONE)) + \
                ' temp difference is ' + str(event_temp_diff))
              if event_temp_diff > 0:
                #Start X minutes earlier for each degree the heating is below the desired temp, plus Y minutes.
                event_time_due_on = event_next_time - datetime.timedelta(0,(event_temp_diff * MINS_PER_DEGREE * 60) + (EFFECT_DELAY * 60))
                logger.debug('Future event needs warm up, due on at ' + str(event_time_due_on.astimezone(LOCAL_TIMEZONE)))
                if time_due_on is None or event_time_due_on < time_due_on or event_time_due_on < current_time:
                  time_due_on = event_time_due_on
                  next_temp = event_desired_temp
                  temp_diff = event_temp_diff
                  logger.debug('Future event starting at ' + str(event_next_time.astimezone(LOCAL_TIMEZONE)) + \
                    ' warm-up, now due on at ' + str(time_due_on.astimezone(LOCAL_TIMEZONE)))
                  #Full blast until 0.3 degrees difference
                  if event_temp_diff > 0.3:
                    new_proportional_time = 30
                elif time_due_on is None or event_next_time < time_due_on:
                  time_due_on = event_next_time
                elif time_due_on is None or event_next_time < time_due_on:
                  time_due_on = event_next_time

          if time_due_on < next_time:
            logger.info('Before an event starting at ' + str(next_time.astimezone(LOCAL_TIMEZONE)) +\
              ' temp diff is ' + str(temp_diff) + ' now due on at ' + str(time_due_on.astimezone(LOCAL_TIMEZONE)))

          if time_due_on <= current_time:
            if temp_diff < 0:
              logger.info('Current temperature ' + str(current_temp) + ' is higher than the desired temperature ' + str(next_temp))
              self.heating_off(0)
            else:
              if new_proportional_time is None:
                #Calculate the proportional amount of time the heating needs to be on to reach the desired temperature
                new_proportional_time = temp_diff * PROPORTIONAL_HEATING_INTERVAL / 2

              if new_proportional_time < MIN_ACTIVE_PERIOD: #Minimum time boiler can be on to be worthwhile
                new_proportional_time = MIN_ACTIVE_PERIOD
              elif new_proportional_time > PROPORTIONAL_HEATING_INTERVAL:
                new_proportional_time = PROPORTIONAL_HEATING_INTERVAL

              #Are we currently on or off?
              if self.relay.one_status(1) == 0 or self.time_on is None: #Off
                if self.time_off is None:
                  time_due_on = next_time
                  new_time_due_on = next_time
                elif new_proportional_time <= self.proportional_time:
                  #Need to be on for less time - turn on in a bit
                  time_due_on = self.time_off + datetime.timedelta(0,(PROPORTIONAL_HEATING_INTERVAL * 60) - (self.proportional_time * 60))
                  new_time_due_on = self.time_off + datetime.timedelta(0,(PROPORTIONAL_HEATING_INTERVAL * 60) - (new_proportional_time * 60))
                else:
                  #Need to be on for more time - turn on now
                  time_due_on = self.time_off + datetime.timedelta(0,(PROPORTIONAL_HEATING_INTERVAL * 60) - (self.proportional_time * 60))
                  new_time_due_on = current_time

                if new_time_due_on <= current_time:
                  logger.info('Heating is off, due on at ' + str(new_time_due_on.astimezone(LOCAL_TIMEZONE)) +'; Turning on')
                  self.heating_on(new_proportional_time)
                else:
                  if new_proportional_time != self.proportional_time:
                    logger.info('Changing time next due on.')
                    self.set_heating_trigger(new_proportional_time, self.relay.one_status(1))
                  if time_due_on != new_time_due_on:
                    logger.info('Heating was off, due on at ' + str(time_due_on.astimezone(LOCAL_TIMEZONE)) +\
                                 '. Now due on at ' + str(new_time_due_on.astimezone(LOCAL_TIMEZONE)))
              else: #On
                time_due_off = self.time_on + datetime.timedelta(0,self.proportional_time * 60)
                if new_proportional_time < PROPORTIONAL_HEATING_INTERVAL:
                  #Must have a time_on at this point
                  new_time_due_off = self.time_on + datetime.timedelta(0,new_proportional_time * 60)
                else:
                  new_time_due_off = next_time_end

                if new_time_due_off < current_time:
                  logger.info('Heating was on, due off at ' + str(time_due_off.astimezone(LOCAL_TIMEZONE)) +'; Turning off')
                  self.heating_off(new_proportional_time)
                else:
                  if new_proportional_time != self.proportional_time:
                    logger.info('Changing time next due off.')
                    self.set_heating_trigger(new_proportional_time, self.relay.one_status(1))
                  if new_time_due_off != time_due_off:
                    logger.info('Heating was on, due off at ' + str(time_due_off.astimezone(LOCAL_TIMEZONE)) +\
                                 '. Now due off at ' + str(new_time_due_off.astimezone(LOCAL_TIMEZONE)))

    self.check_relay_states()
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
    logger.debug('Getting credentials from ' + credential_dir)
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

class NoTemperatureException(Exception):
  def __init__(self):
    super(self, Exception)

if __name__ == '__main__':
  btle.Debugging = True
  logger = logging.getLogger('heating')
  heating = Heating()
  try:
    heating.start()
  except Exception as e:
    logger.exception('Exception in main thread. Exiting.')

    msg = MIMEText('Heating error:\n\n' + str(e))
    msg['Subject'] = 'Heating: Exception in main thread'
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    smtp = smtplib.SMTP(EMAIL_SERVER)
    smtp.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
    smtp.quit()

    if heating.temp_sensors:
      for mac, sensor in heating.temp_sensors.iteritems():
        try:
          sensor.tag._backend.stop()
        except Exception as e1:
          pass

    if heating.relay:
      heating.relay.all_off()

    if heating.http_server:
        heating.http_server.shutdown()

    if heating.sched:
        heating.sched.shutdown(wait = False)

    if isinstance(e, NoTagsFoundException):
      sys.exit(3)
    if isinstance(e, NoTemperatureException):
      sys.exit(2)
    if isinstance(e, KeyboardInterrupt):
      sys.exit(0)
    else:
      sys.exit(1)
