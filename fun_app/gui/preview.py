"""Render individual previews or a time-series contact sheet from an engine."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import time

from PIL import Image, ImageDraw, ImageFont


def load_engine(path):
    spec = importlib.util.spec_from_file_location('extras', path)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    return engine


def render(scene, frame, quantize):
    cols, height = scene.W, scene.H
    if scene.text:
        chars, colors = frame
        image = Image.new('RGB', (cols * 2, height * 4))
        draw = ImageDraw.Draw(image)
        for i, (char, color) in enumerate(zip(chars, colors)):
            if char != ' ':
                y, x = divmod(i, cols)
                draw.rectangle((x*2, y*4, x*2+1, y*4+3),
                               fill=(color >> 16, color >> 8 & 255, color & 255))
        return image
    if quantize:
        frame = [color & scene.mask for color in frame]
    image = Image.new('RGB', (cols, height))
    image.putdata([(color >> 16, color >> 8 & 255, color & 255) for color in frame])
    return image


def rss_kib():
    try:
        with open('/proc/self/status', encoding='ascii') as status:
            return next(int(row.split()[1]) for row in status if row.startswith('VmRSS:'))
    except OSError:
        return None


def series(path, name, size, stamps, seed, measure):
    engine = load_engine(path)
    cls = engine.SCENES[name]
    cols, rows = size
    scene = cls.__new__(cls)
    scene.W, scene.H = cols, rows if cls.text else rows * 2
    scene.rng = engine.random.Random(seed)
    scene.setup()
    encoder = engine.Encoder()
    step = 1 / scene.fps
    dt = min(.1, step)
    ticks = {round(stamp / step): stamp for stamp in stamps}
    images, stats = {}, {}
    baseline = peak = None
    bytes_written = encoded = 0
    monitoring = False
    for tick in range(max(ticks) + 1):
        t = tick * step
        # Keep the actual frame state continuous between snapshots.
        frame = scene.frame(t, dt)
        target = next((stamp for stamp in stamps if stamp - 1 <= t <= stamp), None) if measure else None
        if target is not None:
            if not monitoring:
                encoder.reset()
                bytes_written = encoded = 0
                monitoring = True
            packet = encoder.text(*frame, cols, rows) if scene.text else encoder.blocks(frame, cols, rows, scene.mask)
            if encoded >= 2:
                bytes_written += len(packet)
            encoded += 1
        else:
            monitoring = False
        if tick in ticks:
            stamp = ticks[tick]
            image = render(scene, frame, True)
            images[stamp] = image
            hist = image.convert('L').histogram()
            stats[stamp] = dict(mean=sum(i*n for i,n in enumerate(hist))/sum(hist),
                                dark=sum(hist[:12])/sum(hist), bright=sum(hist[210:])/sum(hist),
                                mbps=bytes_written/max(1,encoded-2)*scene.fps/1e6)
        if measure and t >= 15 and tick % max(1,round(5/step)) == 0:
            rss = rss_kib()
            if rss is not None:
                baseline = rss if baseline is None else baseline
                peak = max(rss, peak or 0)
    return name, size, images, stats, None if baseline is None else peak-baseline


def contact(args, names):
    primary = (118, 49)
    stamps = tuple(sorted(set(args.times)))
    scaled = set(args.scale_scenes) & set(names)
    sizes = ((80,24),(240,60)) if scaled else ()
    tasks = [(args.engine,n,primary,stamps,args.seed,bool(args.metrics)) for n in names]
    tasks.extend((args.engine,n,size,(15,),args.seed,False) for n in names if n in scaled for size in sizes)
    grid = {}
    metrics = {}
    with ProcessPoolExecutor(max_workers=args.jobs) as workers:
        results = [workers.submit(series, *task) for task in tasks]
        for task in results:
            name,size,images,stats,rss = task.result()
            grid[name,size] = images
            if size == primary:
                metrics[name] = dict(samples=stats,rss_growth_kib=rss)
            print(f'{name} {size[0]}x{size[1]} rendered', flush=True)
    columns = [(primary,t) for t in stamps] + [(size,15) for size in sizes]
    width, height, stride = 202, 160, 188
    sheet = Image.new('RGB', (24 + width*len(columns), 48 + stride*len(names)), '#111724')
    pen = ImageDraw.Draw(sheet)
    font = ImageFont.truetype('DejaVuSans.ttf',14)
    for i,(size,t) in enumerate(columns):
        label = f'{t:g} s' if size == primary else f'{size[0]}×{size[1]} · {t:g} s'
        pen.text((12+width*i,12),label,font=font,fill='#b9c8d9')
    for j,name in enumerate(names):
        y = 40+stride*j
        for i,(size,t) in enumerate(columns):
            image = grid.get((name,size),{}).get(t)
            if image is None:
                continue
            scale = min((width-10)/image.width,height/image.height)
            image = image.resize((round(image.width*scale),round(image.height*scale)),Image.Resampling.NEAREST)
            sheet.paste(image,(12+width*i,y))
        pen.text((12,y+height+4),name,font=font,fill='#f0ebe1')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    sheet.save(args.output)
    if args.metrics:
        args.metrics.write_text(json.dumps(metrics,indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('names',nargs='*')
    parser.add_argument('--times',nargs='+',type=float)
    parser.add_argument('--seed',type=int,default=41209)
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--scale-scenes',nargs='*',default=())
    parser.add_argument('--metrics',type=Path)
    parser.add_argument('--single', action='store_true', help='save one deterministic scene thumbnail')
    args = parser.parse_args()
    engine = load_engine(args.engine)
    names = args.names or list(engine.SCENES)
    if args.single:
        if len(names) != 1 or names[0] not in engine.SCENES:
            parser.error('--single requires one active scene')
        _, _, images, _, _ = series(args.engine, names[0], (80, 30), (2.0,), args.seed, False)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        images[2.0].resize((160, 120), Image.Resampling.NEAREST).save(args.output)
        return
    if args.times:
        contact(args,names)
        return
    for name in names:
        scene = engine.make_scene(engine.SCENES[name],118,49)
        dt = 1/scene.fps
        for tick in range(int(14*scene.fps)):
            frame = scene.frame(tick*dt,dt)
        image = render(scene,frame,False)
        image.resize((354,294),Image.Resampling.NEAREST).save(args.output/f'{name}.png')


if __name__ == '__main__':
    main()
