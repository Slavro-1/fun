#!/usr/bin/env python3
"""Exercise the real terminal loop using a PTY that answers kitty graphics queries."""

import argparse
import base64
from concurrent.futures import ProcessPoolExecutor
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import sys
import termios
import time

from gfxdecode import Commands, Decoder, SHM_NAME, live_shm

APC = re.compile(rb'\x1b_G[^\x1b]*\x1b\\')
CSI = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')
RESTORE = b'\x1b[?7h\x1b[?25h\x1b[?1049l'
NORMAL = (118,49,1180,980)
RESIZES = ((90,30,846,570),(24,8,240,160),(240,60,2160,1200),(240,60,2400,1200))


class KittyPeer:
    def __init__(self,fd,transport):
        self.fd = fd
        self.transport = transport
        self.raw = bytearray()
        self.commands = Commands()
        self.decoder = Decoder(self.consume)
        self.pixel_query = False
        self.scanned_pixels = 0
        self.frames = []
        self.events = []
        self.names = set()
        self.queries = []

    def consume(self,name,length):
        pixels = live_shm(name,length)
        (Path('/dev/shm')/name[1:].decode('ascii')).unlink()
        self.names.add(name)
        return pixels

    def pump(self,timeout):
        if not select.select([self.fd],[],[],timeout)[0]:
            return True
        try:
            data = os.read(self.fd,65536)
        except OSError:
            return False
        if not data:
            return False
        self.raw.extend(data)
        for fields,payload in self.commands.feed(data):
            action = fields.get('a')
            if action=='q':
                medium = fields['t']
                self.queries.append(medium)
                if self.transport=='no-reply':
                    continue
                accepted = medium=='d' or self.transport=='shm'
                if accepted and medium=='s':
                    name = base64.b64decode(payload,validate=True)
                    assert SHM_NAME.fullmatch(name)
                    assert self.consume(name,3)==b'\0\0\0'
                status = 'OK' if accepted else 'ENOSYS'
                os.write(self.fd, f'\x1b_Gi={fields["i"]};{status}\x1b\\'.encode())
            elif action=='d':
                assert fields['d']=='I'
                self.events.append(('delete',fields['i']))
            else:
                frame = self.decoder.frame(fields,payload)
                if frame is not None:
                    self.frames.append((frame.fields,frame.size))
                    self.events.append(('frame',frame.fields['i']))
        examined = max(0,self.scanned_pixels-5)
        for match in re.finditer(rb'\x1b\[16t',self.raw[examined:]):
            if examined+match.end()>self.scanned_pixels:
                self.pixel_query = True
                try:
                    os.write(self.fd,b'\x1b[6;22;9t')
                except OSError:
                    return False
        self.scanned_pixels = len(self.raw)
        return True

    def until(self,predicate,seconds=5):
        deadline = time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:
            if not self.pump(.035):
                break
        assert predicate(), 'timed out waiting for a complete terminal frame'


def exercise(engine, name, transport, how, fallback=None):
    pid,fd = pty.fork()
    no_pixels = how=='cell-query'
    if pid==0:
        for key in ('TMUX','STY','SSH_CLIENT','SSH_CONNECTION','SSH_TTY','KITTY_WINDOW_ID','TERM_PROGRAM'):
            os.environ.pop(key,None)
        os.environ.update(TERM='xterm-kitty',FUN_GFX='auto',FUN_RES='med')
        if fallback:
            key,value = fallback
            os.environ[key] = value
        if how=='crash':
            fixture = """
import runpy, sys
scene_name = sys.argv.pop()
engine = runpy.run_path(sys.argv.pop())
cls = engine['SCENES'][scene_name]
render = cls.frame
def broken(self,t,dt):
    if t > .4:
        raise ValueError('simulated rendering failure')
    return render(self,t,dt)
cls.frame = broken
sys.argv += [scene_name]
sys.exit(engine['main']())
"""
            os.execv(sys.executable,[sys.executable,'-I','-c',fixture,engine,name])
        os.execv(sys.executable,[sys.executable,'-I',engine,name])
    def resize(cols,rows,width,height):
        fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack('HHHH',rows,cols,width,height))
        os.kill(pid,signal.SIGWINCH)

    peer = KittyPeer(fd,transport)
    waited = False
    try:
        resize(*NORMAL[:2],*( (0,0) if no_pixels else NORMAL[2:]))
        wants_gfx = name!='matrix' and fallback is None and transport!='no-reply'
        if wants_gfx:
            peer.until(lambda:len(peer.frames)>=2)
            assert peer.queries==['d','s']
            assert peer.pixel_query==no_pixels
            if no_pixels:
                _,(w,h) = peer.frames[-1]
                assert abs(w/h-118*9/(49*22))<.012
        else:
            marker = '▀'.encode()
            if name=='matrix':
                peer.until(lambda: b'\x1b[38;2;' in peer.raw)
            else:
                peer.until(lambda: marker in peer.raw)
            assert not peer.frames
            assert peer.queries==(['d'] if transport=='no-reply' and fallback is None and name!='matrix' else [])
        if how=='resize':
            for geometry in RESIZES:
                cols,rows,width,height = geometry
                start = len(peer.frames)
                delete_start = sum(tag=='delete' for tag,_ in peer.events)
                resize(*geometry)
                if wants_gfx:
                    peer.until(lambda:len(peer.frames)>start and sum(tag=='delete' for tag,_ in peer.events)>delete_start
                               and peer.frames[-1][0]['c']==str(cols)
                               and peer.frames[-1][0]['r']==str(rows)
                               and abs(peer.frames[-1][1][0]/peer.frames[-1][1][1]-width/height)<.027)
                else:
                    peer.until(lambda: f'\x1b[{rows};1H'.encode() in peer.raw)
        if how in ('term','hup','resize','cell-query'):
            os.kill(pid,signal.SIGHUP if how=='hup' else signal.SIGTERM)
        elif how!='crash':
            os.write(fd,b'\x03' if how=='ctrlc' else b'q')
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            if not peer.pump(.035):
                break
        deadline = time.monotonic()+1
        while True:
            end,status = os.waitpid(pid,os.WNOHANG)
            if end:
                break
            if time.monotonic()>=deadline:
                raise AssertionError('child failed to exit')
            time.sleep(.01)
        waited = True
        assert os.waitstatus_to_exitcode(status)==(3 if how=='crash' else 0),bytes(peer.raw[-500:])
        graphics_output = peer.raw
        if how=='crash':
            restored = peer.raw.rfind(RESTORE)
            assert restored>=0
            graphics_output = peer.raw[:restored+len(RESTORE)]
        assert graphics_output.endswith(RESTORE),bytes(peer.raw[-120:])
        if wants_gfx:
            assert not CSI.sub(b'',APC.sub(b'',graphics_output)), 'stray printable bytes in gfx stream'
            assert peer.decoder.fields is None
            assert peer.events[-1][0]=='delete'
            image_ids = {tag['i'] for tag,_ in peer.frames}
            assert len(image_ids)==1
            for tag,_ in peer.frames:
                assert tag['p']=='1' and tag['C']=='1' and tag['q']=='2'
                assert tag['t']==('s' if transport=='shm' else 'd')
            assert all(i in image_ids for _,i in peer.events)
            for name_bytes in peer.names:
                assert not (Path('/dev/shm')/name_bytes[1:].decode('ascii')).exists()
        return f'{name:15} {transport:8} {how:10} OK ({len(peer.frames)} graphics frames)'
    except BaseException as exc:
        raise RuntimeError(f'{name} {transport} {how}: {exc}') from exc
    finally:
        if not waited:
            try:
                os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid,0)
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine',type=Path)
    parser.add_argument('names',help='comma separated list of scene names')
    parser.add_argument('--transport',choices=('shm','zlib'),default='shm')
    parser.add_argument('--mode',choices=('all','term','hup','q','ctrlc','resize','cell-query','crash'),default='all')
    parser.add_argument('--jobs',type=int,default=6)
    parser.add_argument('--fallbacks',action='store_true')
    args = parser.parse_args()
    engine = str(args.engine.resolve())
    modes = ('term','hup','q','ctrlc','resize') if args.mode=='all' else (args.mode,)
    tasks = [(engine,n,args.transport,m) for n in args.names.split(',') for m in modes]
    if args.fallbacks:
        tasks.extend((engine,'plexus','zlib','q',pair) for pair in
                     (('FUN_GFX','0'),('TMUX','test'),('STY','test'),('SSH_TTY','test'),('TERM','xterm-256color')))
        tasks.extend(((engine,'plexus','no-reply','q'),(engine,'plexus','shm','cell-query')))
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        jobs = [pool.submit(exercise,*task) for task in tasks]
        errors = 0
        for job in jobs:
            try:
                print(job.result(),flush=True)
            except Exception as exc:
                print(f'FAIL {exc}',flush=True)
                errors += 1
    print(f'FAILURES: {errors}',flush=True)
    raise SystemExit(bool(errors))


if __name__=='__main__':
    main()
