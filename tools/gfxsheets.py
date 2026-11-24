#!/usr/bin/env python3
"""Compare block and decoded kitty output in one contact sheet per batch."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from gfxdecode import Commands, Decoder
from snap import load_engine, render

SIZE = 118,49
TIMES = 2,12
SEED = 41209


def pair(engine_path,name):
    engine = load_engine(engine_path)
    cls = engine.SCENES[name]
    cols,rows = SIZE
    panels = []
    for gfx in (False,True):
        if gfx and not cls.text:
            W,H = engine._gfx_size(cls,*SIZE,cols*10,rows*20,'med')
        else:
            W,H = cols,rows if cls.text else rows*2
        scene = cls.__new__(cls)
        scene.W,scene.H = W,H
        scene.S = H/(rows*2) if gfx and not cls.text else 1.
        scene.gfx = gfx and not cls.text
        scene.rng = engine.random.Random(SEED)
        scene.setup()
        if scene.gfx:
            scene.fps = cls.gfx_fps
        step = 1/scene.fps
        dt = min(.1,step)
        ticks = {round(s/step) for s in TIMES}
        graphics = engine.KittyGraphics()
        for i in range(max(ticks)+1):
            pixels = scene.frame(i*step,dt)
            if i not in ticks:
                continue
            if scene.gfx:
                stream = graphics.packet(pixels,W,H,cols,rows)
                commands,decoder = Commands(),Decoder()
                frames = [frame for fields,payload in commands.feed(stream)
                          if (frame:=decoder.frame(fields,payload)) is not None]
                assert len(frames)==1 and frames[0].size==(W,H)
                panels.append(frames[0].image())
            else:
                panels.append(render(scene,pixels,True))
    return name,panels


def write_sheet(output, group):
    width,height,frame_width,row_height = 1000,196,236,227
    canvas = Image.new('RGB',(width,43+row_height*len(group)),'#121927')
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf',15)
    except OSError:
        font = ImageFont.load_default()
    labels = [f'{mode}  /  {t} s' for mode in ('Half-block','Kitty RGB') for t in TIMES]
    for i,label in enumerate(labels):
        draw.text((12+247*i,12),label,fill='#b6c4d8',font=font)
    for row,(name,images) in enumerate(group):
        y = 42+row_height*row
        for i,image in enumerate(images):
            if i>=2 and name!='matrix':
                resized = image.resize((frame_width,height),Image.Resampling.BICUBIC)
            else:
                resized = image.resize((frame_width,height),Image.Resampling.NEAREST)
            canvas.paste(resized,(12+247*i,y))
        draw.text((12,y+height+5),name,fill='#eee9df',font=font)
    canvas.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--batch',type=int,choices=range(1,9))
    args = parser.parse_args()
    names = list(load_engine(args.engine).SCENES)
    args.output.mkdir(parents=True,exist_ok=True)
    with ProcessPoolExecutor(max_workers=6) as workers:
        for start in range(0,len(names),6):
            batch = start//6+1
            if args.batch is not None and batch!=args.batch:
                continue
            work = [workers.submit(pair,args.engine,n) for n in names[start:start+6]]
            write_sheet(args.output/f'compare-{batch}.png',[job.result() for job in work])
            print(f'Batch {batch} rendered',flush=True)


if __name__=='__main__':
    main()
