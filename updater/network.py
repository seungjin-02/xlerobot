"""Explicit opt-in LAN HTTPS; loopback HTTP remains the default."""
import ipaddress
import os
import subprocess
from pathlib import Path
import ssl

from common import UpdateError


def lan_address(value):
    try:
        address = ipaddress.IPv4Address(value)
    except (ValueError, TypeError):
        raise UpdateError('private_ipv4_required') from None
    if not any(address in ipaddress.ip_network(net) for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
        raise UpdateError('private_ipv4_required')
    return str(address)


def tls_context(cert, key):
    for name in (cert, key):
        path = Path(name)
        if not path.is_absolute() or path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
            raise UpdateError('root_owned_tls_files_required')
    if Path(key).stat().st_mode & 0o077:
        raise UpdateError('private_tls_key_required')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    return context


def verify_certificate_ip(cert, address):
    # OpenSSL 3.0 and 3.5 differ on mismatch exit status. Both must fail closed.
    try:
        result = subprocess.run(['openssl', 'x509', '-in', str(cert), '-noout', '-checkip', address],
            check=False, capture_output=True, text=True, env={**os.environ, 'LC_ALL':'C'}, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        raise UpdateError('certificate_check_failed') from None
    if result.returncode != 0 or result.stdout.strip() != 'IP '+address+' does match certificate':
        raise UpdateError('certificate_ip_mismatch')
