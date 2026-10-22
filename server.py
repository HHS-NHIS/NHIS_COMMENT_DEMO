#!/usr/bin/env python3
"""Zero-dependency, read-only Railway server for the frozen NHIS V10.6 management backup."""
import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

INDEX = (Path(__file__).resolve().parent / 'index.html').read_bytes()
SHA = hashlib.sha256(INDEX).hexdigest()
VERSION = 'NHIS-V10.6-STATIC-MANAGEMENT-3748'

class Handler(BaseHTTPRequestHandler):
    server_version = 'NHIS-Static'
    sys_version = ''

    def respond(self, head=False):
        path = urlsplit(self.path).path
        if path in ('/', '/index.html', '/management', '/management/'):
            status, payload, mime = 200, INDEX, 'text/html; charset=utf-8'
        elif path in ('/healthz', '/version'):
            status = 200
            payload = (json.dumps({'status':'ok','version':VERSION,'comments':3748,
                'management_sections':8,'themes':30,'combinations':240,
                'html_sha256':SHA},separators=(',',':'))+'\n').encode('utf-8')
            mime = 'application/json; charset=utf-8'
        else:
            status, payload, mime = 404, b'Not found\n', 'text/plain; charset=utf-8'
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Cache-Control', 'no-store, max-age=0')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; form-action 'none'")
        self.end_headers()
        if not head:
            self.wfile.write(payload)

    def do_GET(self): self.respond()
    def do_HEAD(self): self.respond(head=True)
    def do_POST(self):
        self.send_response(405)
        self.send_header('Allow','GET, HEAD')
        self.send_header('Content-Length','0')
        self.end_headers()

if __name__ == '__main__':
    port = int(os.getenv('PORT', '8080'))
    if not 1 <= port <= 65535: raise ValueError('Invalid PORT')
    print(f'{VERSION} listening on 0.0.0.0:{port}',flush=True)
    ThreadingHTTPServer(('0.0.0.0',port), Handler).serve_forever()
