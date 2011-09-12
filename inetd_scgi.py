"""
Copyright (c) 2011, Barry Pederson <bp@barryp.org>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

    1. Redistributions of source code must retain the above copyright
       notice, this list of conditions and the following disclaimer.

    2. Redistributions in binary form must reproduce the above copyright
       notice, this list of conditions and the following disclaimer in the
       documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

------------

Single-shot SCGI->WSGI server, expected to be run by inetd so that the
link back to the client is through stdin/stdout

For Python 2.6 and higher (including 3.x)
  To patch for Python 2.5 and lower, just replace "b'" with "'"

2011-01-27 Barry Pederson <bp@barryp.org>

"""
import sys

__all__ = [
    'ProtocolError',
    'run_app',
    ]


def debug(msg):
    sys.stderr.write(msg+'\n')


class ProtocolError(Exception):
    pass


def read_netstring(f):
    """
    Read a SCGI netstring from the file-type object 'f'

    """
    size = b''
    while True:
        ch = f.read(1)
        if ch == b':':
            break
        elif ch in b'0123456789':
            size += ch
        else:
            raise ProtocolError('Invalid netstring length: [%s%s]' % (size.decode('latin-1'), ch.decode('latin-1')))
    size = int(size)
    data = []
    while size:
        s = f.read(size)
        if not s:
            raise ProtocolError('EOF reading netstring')
        data.append(s)
        size -= len(s)
    return b''.join(data)


class SCGIConnection(object):
    def __init__(self, in_f, out_f):
        self.in_f = in_f
        self.out_f = out_f

        self.status = None
        self.response_headers = None
        self.response_headers_sent = False


    def run(self, app):
        headers = read_netstring(self.in_f).split(b'\x00')[:-1]
        environ = dict((str(headers[i].decode('latin-1')), str(headers[i+1].decode('latin-1'))) for i in range(0,len(headers),2))
        environ['wsgi.input']        = self.in_f
        environ['wsgi.errors']       = sys.stderr
        environ['wsgi.version']      = (1, 0)
        environ['wsgi.multithread']  = False
        environ['wsgi.multiprocess'] = False
        environ['wsgi.run_once']     = True

        if environ.get('HTTPS', 'off') in ('on', '1'):
            environ['wsgi.url_scheme'] = 'https'
        else:
            environ['wsgi.url_scheme'] = 'http'

        result = app(environ, self.start_response)

        try:
            for data in result:
                if data:
                    # Only call write if there's actually something to write,
                    # because this will also trigger sending of response_headers
                    self.write(data)
        finally:
            if hasattr(result, 'close'):
                result.close()

        if not self.response_headers_sent:
            # The app never returned any body, so trigger sending
            # of headers by calling an empty write
            self.write(b'')

    def start_response(self, status, response_headers, exc_info=None):
        self.status = status
        self.response_headers = response_headers
        return self.write

    def write(self, data):
        if not self.response_headers_sent:
            self.out_f.write(('Status: %s\r\n' % self.status).encode('latin-1'))
            for h in self.response_headers:
                self.out_f.write(('%s: %s\r\n' % h).encode('latin-1'))
            self.out_f.write(b'\r\n')
            self.response_headers_sent = True

        self.out_f.write(data)
        self.out_f.flush()


def run_app(app, stderr=None):
    """
    Run a WSGI application for one request over stdin/stdout using the SCGI
    protocol, redirecting stderr to the supplied file or filename,
    (or /dev/null if None).

    """
    #
    # For Python 3.x, change stdin/stderr to binary mode
    #
    if sys.version_info.major >= 3:
        sys.stdin = sys.stdin.detach()
        sys.stdout = sys.stdout.detach()

    if isinstance(stderr, str):
        sys.stderr = open(stderr, 'a')
    elif hasattr(stderr, 'write'):
        sys.stderr = stderr
    else:
        sys.stderr = open('/dev/null', 'w')

    SCGIConnection(sys.stdin, sys.stdout).run(app)
