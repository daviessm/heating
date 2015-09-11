import httplib2, logging

from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from SocketServer import ThreadingMixIn

logger = logging.getLogger('heating')

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

