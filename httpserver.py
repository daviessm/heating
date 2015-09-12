import httplib2, logging, urlparse, pytz, datetime

from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from SocketServer import ThreadingMixIn

logger = logging.getLogger('heating')

class HttpHandler(BaseHTTPRequestHandler):
  heating = None

  def do_GET(self):
    parsed_path = urlparse.urlparse(self.path)
    if parsed_path.path == '/current_temp':
      logger.debug('Web request for /current_temp, sending ' + str(self.heating.current_temp))
      self.send_response(200)
      self.end_headers()
      self.wfile.write(str(self.heating.current_temp) + '\n')
    elif parsed_path.path == '/desired_temp':
      if not self.heating.next_event or self.heating.next_event[0] > pytz.utc.localize(datetime.datetime.utcnow()):
        desired_temp = str(self.heating.minimum_temp)
      else:
        desired_temp = str(self.heating.next_event[2])
      logger.debug('Web request for /desired_temp, sending ' + desired_temp)
      self.send_response(200)
      self.end_headers()
      self.wfile.write(desired_temp + '\n')
    elif parsed_path.path == '/proportion':
      logger.debug('Web request for /proportion, sending ' + str(self.heating.proportional_time))
      self.send_response(200)
      self.end_headers()
      self.wfile.write(str(self.heating.proportional_time) + '\n')
    else:
      logger.debug('Web request for ' + parsed_path.path + ', ignoring')
      self.send_error(404)
    return

  def log_message(self, format, *args):
    return

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
  '''Handle requests in a separate thread.'''

