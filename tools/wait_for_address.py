#!/usr/bin/env python3
"""Wait for the configured local admin address without changing its exposure."""
import errno
import ipaddress
import json
from pathlib import Path
import socket
import time


def wait_for_address(address, timeout=60., *, clock=time.monotonic, sleep=time.sleep, factory=socket.socket):
    ip=ipaddress.ip_address(address)
    if ip.version!=4 or not (ip.is_private or ip.is_loopback):raise ValueError('Expected local IPv4 address')
    deadline=clock()+timeout
    while True:
        try:
            with factory(socket.AF_INET,socket.SOCK_STREAM) as probe:probe.bind((str(ip),0))
            return
        except OSError as error:
            if error.errno!=errno.EADDRNOTAVAIL:raise
            if clock()>=deadline:raise TimeoutError('Configured admin address did not become available') from error
            sleep(min(.25,max(0.,deadline-clock())))


if __name__=='__main__':
    policy=json.loads(Path('/etc/lekiwi-updater/policy.json').read_text())
    wait_for_address(policy.get('admin_address') or '127.0.0.1')
