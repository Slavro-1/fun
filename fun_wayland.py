"""Small input-free Wayland client for ext-idle-notify-v1.

Only registry discovery, wl_display.sync, wl_seat v1, and the inhibitor-aware
v1 notification are used. None of these messages carries file descriptors.
Closing this dedicated connection destroys all its protocol objects.
"""
import math
import os
import select
import socket
import struct
import time


def uints(*values):
    return struct.pack('=' + 'I' * len(values), *values)


def string(value):
    data = value.encode('ascii') + b'\0'
    return uints(len(data)) + data.ljust((len(data) + 3) & ~3, b'\0')


class Wayland:
    name = 'Wayland ext-idle-notify-v1'
    registry, notifier, seat, notification = 2, 4, 5, 6

    def __init__(self, threshold):
        display = os.environ.get('WAYLAND_DISPLAY')
        if not display:
            raise OSError('WAYLAND_DISPLAY missing in login environment')
        if not os.path.isabs(display):
            runtime = os.environ.get('XDG_RUNTIME_DIR')
            if not runtime:
                raise OSError('XDG_RUNTIME_DIR missing')
            display = os.path.join(runtime, display)
        self.sock = socket.socket(socket.AF_UNIX)
        self.threshold = threshold
        self.globals = {}
        self.bound = set()
        self.buffer = bytearray()
        self.is_idle = False
        self.seen_idle = self.seen_resume = False
        self.done = None
        try:
            self.sock.settimeout(2)
            self.sock.connect(display)
            self.send(1, 1, uints(self.registry))  # wl_display.get_registry
            self.sync(3)
            self.bind('ext_idle_notifier_v1', self.notifier)
            self.bind('wl_seat', self.seat)
            # get_idle_notification honors compositor inhibitors at every version.
            self.send(self.notifier, 1, uints(self.notification, math.ceil(threshold * 1000), self.seat))
            self.sync(7)
        except BaseException:
            self.close()
            raise

    def send(self, obj, opcode, args):
        self.sock.sendall(uints(obj, ((8 + len(args)) << 16) | opcode) + args)

    def bind(self, interface, obj):
        ids = [i for i, (name, version) in self.globals.items() if name == interface and version >= 1]
        if len(ids) != 1:
            raise OSError(f'{interface}: expected one compatible global, found {len(ids)}')
        self.bound.add(ids[0])
        self.send(self.registry, 0, uints(ids[0]) + string(interface) + uints(1, obj))

    def sync(self, callback):
        self.send(1, 0, uints(callback))
        deadline = time.monotonic() + 2
        while self.done != callback:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OSError('Wayland registry/notification handshake timed out')
            self.pump(remaining)

    def pump(self, timeout):
        if not select.select([self.sock], [], [], timeout)[0]:
            return False
        chunk = self.sock.recv(65536)
        if not chunk:
            raise ConnectionError('compositor disconnected')
        self.buffer.extend(chunk)
        resumed = False
        while len(self.buffer) >= 8:
            obj, header = struct.unpack_from('=II', self.buffer)
            size, opcode = header >> 16, header & 65535
            if size < 8 or size % 4:
                raise OSError('invalid Wayland event size')
            if len(self.buffer) < size:
                break
            data = self.buffer[8:size]
            del self.buffer[:size]
            if obj == 1 and opcode == 0:
                raise OSError('compositor rejected Wayland request')
            if obj == self.registry and opcode == 0:
                number, length = struct.unpack_from('=II', data)
                interface = data[8:8 + length - 1].decode('ascii')
                version, = struct.unpack_from('=I', data, 8 + ((length + 3) & ~3))
                self.globals[number] = interface, version
                if self.bound and interface == 'wl_seat':
                    raise OSError('seat configuration changed')
            elif obj == self.registry and opcode == 1:
                number, = struct.unpack('=I', data)
                self.globals.pop(number, None)
                if number in self.bound:
                    raise OSError('seat or idle notifier removed')
            elif obj in (3, 7) and opcode == 0:
                self.done = obj
            elif obj == self.notification:
                if opcode == 0:
                    self.seen_idle = self.is_idle = True
                elif opcode == 1:
                    self.is_idle = False
                    self.seen_resume = resumed = True
        return resumed

    def idle(self):
        return self.threshold if self.is_idle else 0

    @property
    def evidence(self):
        if self.seen_resume:
            return 'idled and resumed observed'
        if self.seen_idle:
            return 'idled observed; awaiting resumed'
        return 'subscribed (v1); awaiting compositor idled event'

    def close(self):
        self.sock.close()
