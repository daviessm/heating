import httplib2, logging, urlparse, pytz, datetime

from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from SocketServer import ThreadingMixIn

logger = logging.getLogger('heating')

class HttpHandler(BaseHTTPRequestHandler):
  heating = None

  def do_GET(self):
    parsed_path = urlparse.urlparse(self.path)
    if '/current_temp/' in parsed_path.path:
      address = parsed_path.path[parsed_path.path.rfind('/') + 1:]
      if address in self.heating.temp_sensors:
        response = str(self.heating.temp_sensors[address].amb_temp) + '\n'
        logger.info('Web request for ' + parsed_path.path + ', sending ' + response)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(response)
      else:
        logger.info('Web request for ' + parsed_path.path + ', sending 404')
        self.send_error(404)
    elif '/current_temp' in parsed_path.path:
      response = ''
      for mac, sensor in self.heating.temp_sensors.iteritems():
        response += mac + '=' + str(self.heating.temp_sensors[mac].amb_temp) + '\n'
      logger.info('Web request for /current_temp, sending ' + response)
      self.send_response(200)
      self.end_headers()
      self.wfile.write(response)
    elif parsed_path.path == '/desired_temp':
      logger.info('Web request for /desired_temp, sending ' + str(self.heating.desired_temp))
      self.send_response(200)
      self.end_headers()
      self.wfile.write(str(self.heating.desired_temp) + '\n')
    elif parsed_path.path == '/proportion':
      logger.info('Web request for /proportion, sending ' + str(self.heating.proportional_time))
      self.send_response(200)
      self.end_headers()
      self.wfile.write(str(self.heating.proportional_time) + '\n')
    elif parsed_path.path == '/heating_status':
      logger.info('Web request for /heating_status, sending ' + str(self.heating.relay.status))
      self.send_response(200)
      self.end_headers()
      self.wfile.write(str(self.heating.relay.status) + '\n')
    else:
      logger.info('GET request for ' + parsed_path.path + ', ignoring')
      self.send_error(404)
    return

  def do_POST(self):
    parsed_path = urlparse.urlparse(self.path)
    if parsed_path.path == '/refresh/events':
      logger.info('Web request for /refresh/events')
      logger.debug('Request data: ' + str(str(self.headers).splitlines()))
      try:
        if self.headers.getheader('X-Goog-Resource-State') != 'sync':
          self.heating.get_next_event()
          self.send_response(200)
      except Exception as e:
        self.send_response(500)
        self.end_headers()
        raise
      self.end_headers()
    else:
      logger.info('POST request for ' + parsed_path.path + ', ignoring')
      self.send_error(404)

  def log_message(self, format, *args):
    return

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
  '''Handle requests in a separate thread.'''
  def shutdown(self):
    self.socket.close()
    HTTPServer.shutdown(self)
