import httplib2, logging, urlparse, pytz, datetime

from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from SocketServer import ThreadingMixIn

logger = logging.getLogger('heating')

class HttpHandler(BaseHTTPRequestHandler):
  heating = None

  def do_GET(self):
    parsed_path = urlparse.urlparse(self.path)
    if '/current_temp' in parsed_path.path:
      address = parsed_path.path[parsed_path.path.rfind('/') + 1:]
      if address in self.heating.temp_sensors:
        response = str(self.heating.temp_sensors[address].amb_temp) + '\n'
      else:
        response = ''
        for mac, sensor in self.heating.temp_sensors.iteritems():
          response += mac + '=' + str(self.heating.temp_sensors[mac].amb_temp) + '\n'
      logger.info('Web request for ' + parsed_path.path + ', sending ' + response.replace('\n','\\n '))
      self.send_response(200)
      self.end_headers()
      self.wfile.write(response)
    elif parsed_path.path == '/desired_temp':
      if not self.heating.next_event or self.heating.next_event[0] > pytz.utc.localize(datetime.datetime.utcnow()):
        desired_temp = str(self.heating.minimum_temp)
      else:
        desired_temp = str(self.heating.next_event[2])
      logger.info('Web request for /desired_temp, sending ' + desired_temp)
      self.send_response(200)
      self.end_headers()
      self.wfile.write(desired_temp + '\n')
    elif parsed_path.path == '/proportion':
      logger.info('Web request for /proportion, sending ' + str(self.heating.proportional_time))
      self.send_response(200)
      self.end_headers()
      self.wfile.write(str(self.heating.proportional_time) + '\n')
    elif parsed_path.path == '/refresh/events':
      logger.info('Web request for /refresh/events, sending ' + str(self.heating.next_event))
      self.heating.get_next_event()
      self.send_response(200)
      self.end_headers()
      self.wfile.write(str(self.heating.next_event) + '\n')
    else:
      logger.info('Web request for ' + parsed_path.path + ', ignoring')
      self.send_error(404)
    return

  def log_message(self, format, *args):
    return

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
  '''Handle requests in a separate thread.'''

