import httplib2, logging, urllib.parse, pytz, datetime

from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

logger = logging.getLogger('heating')

class HttpHandler(BaseHTTPRequestHandler):
  heating = None

  def do_GET(self):
    parsed_path = urllib.parse.urlparse(self.path)
    if '/current_temp/' in parsed_path.path:
      address = parsed_path.path[parsed_path.path.rfind('/') + 1:]
      if address in self.heating.temp_sensors:
        response = str(self.heating.temp_sensors[address].amb_temp) + '\n'
        logger.info('Web request for ' + parsed_path.path + ', sending ' + response)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(bytes(response, 'UTF-8'))
      else:
        logger.info('Web request for ' + parsed_path.path + ', sending 404')
        self.send_error(404)
    elif '/current_temp' in parsed_path.path:
      response = ''
      for mac, sensor in self.heating.temp_sensors.items():
        response += mac + '=' + str(self.heating.temp_sensors[mac].amb_temp) + '\n'
      logger.info('Web request for /current_temp, sending ' + response)
      self.send_response(200)
      self.end_headers()
      self.wfile.write(bytes(response, 'UTF-8'))
    elif parsed_path.path == '/desired_temp':
      logger.info('Web request for /desired_temp, sending ' + str(self.heating.desired_temp))
      self.send_response(200)
      self.end_headers()
      self.wfile.write(bytes(str(self.heating.desired_temp) + '\n', 'UTF-8'))
    elif parsed_path.path == '/proportion':
      logger.info('Web request for /proportion, sending ' + str(self.heating.proportional_time))
      self.send_response(200)
      self.end_headers()
      self.wfile.write(bytes(str(self.heating.proportional_time) + '\n', 'UTF-8'))
    elif parsed_path.path == '/heating_status':
      status_num = '0'
      if self.heating.relays_heating._status:
        status_num = '1'
      logger.info('Web request for /heating_status, sending ' + status_num)
      self.send_response(200)
      self.end_headers()
      self.wfile.write(bytes(status_num + '\n', 'UTF-8'))
    elif parsed_path.path == '/preheat_status':
      status_num = '0'
      if self.heating.relays_preheat._status:
        status_num = '1'
      logger.info('Web request for /preheat_status, sending ' + status_num)
      self.send_response(200)
      self.end_headers()
      self.wfile.write(bytes(status_num + '\n', 'UTF-8'))
    elif parsed_path.path == '/outside_temp':
      logger.info('Web request for /outside_temp, sending ' + str(self.heating.outside_temp))
      self.send_response(200)
      self.end_headers()
      self.wfile.write(bytes(str(self.heating.outside_temp) + '\n', 'UTF-8'))
    elif parsed_path.path == '/outside_apparent_temp':
      logger.info('Web request for /outside_apparent_temp, sending ' + str(self.heating.outside_apparent_temp))
      self.send_response(200)
      self.end_headers()
      self.wfile.write(bytes(str(self.heating.outside_apparent_temp) + '\n', 'UTF-8'))
    else:
      logger.info('GET request for ' + parsed_path.path + ', ignoring')
      self.send_error(404)
    return

  def do_POST(self):
    parsed_path = urllib.parse.urlparse(self.path)
    if parsed_path.path == '/refresh/events':
      logger.info('Web request for /refresh/events')
      logger.debug('Request data: ' + str(str(self.headers).splitlines()))
      try:
        if self.headers.get('X-Goog-Resource-State') != 'sync' and \
            self.headers.get('X-Goog-Channel-ID') == self.heating.event_sync_id:
          self.heating.get_next_event()
        self.send_response(204)
        self.end_headers()
      except Exception as e:
        self.send_response(500)
        self.end_headers()
        raise
    else:
      logger.info('POST request for ' + parsed_path.path + ', ignoring')
      self.send_error(404)
    return

  def log_message(self, format, *args):
    return

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
  '''Handle requests in a separate thread.'''
  def shutdown(self):
    self.socket.close()
    HTTPServer.shutdown(self)
