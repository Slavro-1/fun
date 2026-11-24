#!/usr/bin/env python3
"""Decode raw RGB kitty graphics packets into PNGs (Pillow needed to save)."""

import argparse
import base64
from dataclasses import dataclass
from pathlib import Path
import re
import zlib

START = b'\x1b_G'
END = b'\x1b\\'
MAX_PIXELS = 500_000  # includes rounded ultra-tier dimensions
MAX_PAYLOAD = 2_050_000  # base64 RGB plus compression overhead
SHM_NAME = re.compile(rb'/fun-[a-f0-9]{12}-[1-9][0-9]*\Z')


class Commands:
    """Split kitty APCs even when the transport splits an escape sequence."""

    def __init__(self):
        self.pending = b''

    def feed(self, data):
        self.pending += data
        while True:
            start = self.pending.find(START)
            if start < 0:
                self.pending = self.pending[-2:]
                return
            end = self.pending.find(END, start+len(START))
            if end < 0:
                self.pending = self.pending[start:]
                if len(self.pending) > 8192:
                    raise ValueError('unterminated graphics escape')
                return
            header, separator, payload = self.pending[start+len(START):end].partition(b';')
            self.pending = self.pending[end+len(END):]
            if not separator:
                raise ValueError('graphics escape missing its payload separator')
            fields = dict(item.split('=',1) for item in header.decode('ascii').split(','))
            yield fields,payload


@dataclass(frozen=True)
class ImageFrame:
    fields: dict
    pixels: bytes

    @property
    def size(self):
        return int(self.fields['s']),int(self.fields['v'])

    def image(self):
        from PIL import Image

        return Image.frombytes('RGB',self.size,self.pixels)


class Decoder:
    def __init__(self, shared_reader=None):
        self.shared_reader = shared_reader
        self.fields = None
        self.chunks = bytearray()

    def frame(self, fields, payload):
        if fields.get('a') in ('q','d','p'):
            return None
        if len(payload)>4096:
            raise ValueError('oversize graphics chunk')
        if self.fields is None:
            if fields.get('a') != 'T' or fields.get('f') != '24':
                raise ValueError(f'expected an RGB transmit-and-display command: {fields}')
            width,height = int(fields['s']),int(fields['v'])
            if not 0<width*height<=MAX_PIXELS or min(width,height)<1:
                raise ValueError('graphics dimensions outside decoder limits')
            if fields.get('t') == 's':
                length = width*height*3
                name = base64.b64decode(payload,validate=True)
                if not SHM_NAME.fullmatch(name) or int(fields['S']) != length:
                    raise ValueError('invalid shared frame reference')
                if self.shared_reader is None:
                    raise ValueError('shared frame needs a live SHM reader')
                pixels = self.shared_reader(name,length)
                if len(pixels)!=length:
                    raise ValueError('short shared frame')
                return ImageFrame(fields,pixels)
            self.fields = fields
        elif set(fields)-{'m','q'}:
            raise ValueError('unexpected fields on continuation chunk')
        self.chunks.extend(payload)
        if len(self.chunks)>MAX_PAYLOAD:
            raise ValueError('graphics payload exceeds decoder limit')
        if fields.get('m') == '1':
            return None
        header,self.fields = self.fields,None
        data = base64.b64decode(self.chunks,validate=True)
        self.chunks.clear()
        expected = int(header['s'])*int(header['v'])*3
        if header.get('o') == 'z':
            stream = zlib.decompressobj()
            pixels = stream.decompress(data,expected+1)
            if not stream.eof or stream.unused_data:
                raise ValueError('invalid compressed frame')
        else:
            pixels = data
        if len(pixels)!=expected:
            raise ValueError('decoded RGB length differs from frame dimensions')
        return ImageFrame(header,pixels)


def live_shm(name,length):
    """Read a Linux shared-memory frame before kitty unlinks it."""
    with (Path('/dev/shm') / name[1:].decode('ascii')).open('rb') as stream:
        return stream.read(length)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--limit',type=int,default=20)
    parser.add_argument('--live-shm',action='store_true')
    args = parser.parse_args()
    commands = Commands()
    decoder = Decoder(live_shm if args.live_shm else None)
    args.output.mkdir(parents=True,exist_ok=True)
    count = 0
    with args.capture.open('rb') as source:
        while count<args.limit and (chunk:=source.read(16384)):
            for fields,payload in commands.feed(chunk):
                frame = decoder.frame(fields,payload)
                if frame is None:
                    continue
                count += 1
                frame.image().save(args.output/f'frame-{count:04}.png')
                if count==args.limit:
                    break
    if not count:
        parser.exit(1,'No complete RGB frames were found.\n')
    print(f'Decoded {count} frame(s) to {args.output}')


if __name__=='__main__':
    main()
