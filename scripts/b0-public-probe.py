"""Private synthetic TLS reachability probe, no application or model access."""
import http.server
import ssl
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / '.local/phase2/b0/completion-20261028/network'


class Probe(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/health':
            self.send_error(404)
            return
        body = b'{"fixture":"agent-memory-public-reachability"}'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        print('probe peer=' + self.client_address[0], flush=True)

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(('127.0.0.1', 18443), Probe)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(ROOT / 'cert.pem', ROOT / 'key.pem')
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
