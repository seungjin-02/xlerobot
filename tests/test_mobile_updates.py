"""LAN admin authentication over real TLS; no root provisioning or robot access."""
import hashlib
import http.cookiejar
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'updater'))
sys.path.insert(0, str(ROOT/'app'))
from common import UpdateError
from daemon import Admin, Handler
from network import lan_address, tls_context, verify_certificate_ip
from maintenance import Maintenance


class MobileTests(unittest.TestCase):
    def test_lan_listener_requires_explicit_private_ipv4(self):
        for value in ('10.42.0.141', '192.168.4.1', '172.16.0.2'):
            self.assertEqual(lan_address(value), value)
        for value in ('0.0.0.0', '127.0.0.1', '8.8.8.8', '169.254.1.1', 'example.com', '::1', '10.1.1.999', None):
            with self.subTest(value=value), self.assertRaises(UpdateError):
                lan_address(value)

    def test_tls_files_reject_unprotected_keys_or_untrusted_ownership(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert, key = Path(tmp)/'cert.pem', Path(tmp)/'key.pem'
            for p in (cert, key):
                p.write_text('invalid');p.chmod(0o666)
            with self.assertRaises(UpdateError):
                tls_context(str(cert), str(key))

    def test_mobile_url_advertised_only_when_configured(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            m = Maintenance(tmp, required=False)
            self.assertNotIn('admin_url', m.status())
            with patch.dict(os.environ, {'LEKIWI_ADMIN_URL':'https://192.168.4.1:8093'}):
                self.assertEqual(m.status()['admin_url'], 'https://192.168.4.1:8093')
                self.assertFalse(m.status()['enabled'])

    def test_real_tls_login_secure_cookie_origin_and_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert, key = Path(tmp)/'cert.pem', Path(tmp)/'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                '-keyout', str(key), '-out', str(cert), '-days', '1',
                '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1'],
                check=True, capture_output=True)
            verify_certificate_ip(cert, '127.0.0.1')
            with self.assertRaisesRegex(UpdateError, 'certificate_ip_mismatch'):
                verify_certificate_ip(cert, '192.168.4.1')
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(cert, key)
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
            host = '127.0.0.1:'+str(server.server_port)
            server.secure_admin = True;server.allowed_hosts = (host,)
            password, salt = 'separate-mobile-fixture', '12'*16
            hashed = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
            server.admin = Admin(object(), hashed, salt)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
            # Trust only this fixture's self-signed certificate, not a global trust bypass.
            trusted = ssl.create_default_context(cafile=str(cert))
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                urllib.request.HTTPSHandler(context=trusted),
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            def post(path, body, origin='https://'+host, target_host=host):
                return client.open(urllib.request.Request('https://'+host+path,
                    data=json.dumps(body).encode(),
                    headers={'Content-Type':'application/json', 'Origin':origin, 'Host':target_host}), timeout=5)
            for origin, target_host in (('http://'+host, host), ('https://attacker.invalid', host),
                    ('https://'+host, 'attacker.invalid')):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    post('/api/login', {'password':password}, origin, target_host)
                self.assertEqual(error.exception.code, 403)
            with post('/api/login', {'password':password}) as response:
                self.assertIn('; Secure', response.headers['Set-Cookie'])
            with post('/api/logout', {}) as response:
                self.assertIn('Max-Age=0; Secure', response.headers['Set-Cookie'])
            with self.assertRaises(urllib.error.HTTPError) as error:
                post('/api/apply', {'tag':'v2.0.0', 'commit':'b'*40, 'motor_power_isolated':True})
            self.assertEqual(error.exception.code, 401)


if __name__ == '__main__':
    unittest.main()
