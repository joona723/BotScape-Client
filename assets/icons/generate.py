"""Rebuild the hand-authored SVG icon set as transparent, 8x-sampled PNGs.

Only Pillow is required. Run from any directory: python assets/icons/generate.py
The small SVG renderer supports the filled shapes used by these sources.
"""
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
GREEN = '#3fb96b'
GOLD = '#dc8a00'
SOURCES = {
    'play': f'<path fill="{GREEN}" d="M 10 5.5 Q 8 4.3 8 6.6 L 8 25.4 Q 8 27.7 10 26.5 L 25.2 17.5 Q 27.5 16 25.2 14.5 Z"/>',
    'stop': '<rect x="6" y="6" width="20" height="20" rx="3" fill="#e05a52"/>',
    'reload': '<path fill="#b8bec7" d="M 25.8 7.4 L 29 4.2 L 29 14 L 19.2 14 L 23.5 9.7 C 21.8 7.7 19.1 6.5 16 6.5 C 10.8 6.5 6.5 10.8 6.5 16 C 6.5 21.2 10.8 25.5 16 25.5 C 20.4 25.5 24.1 22.5 25.2 18.5 L 28.3 19.3 C 26.9 24.7 21.9 29 16 29 C 8.8 29 3 23.2 3 16 C 3 8.8 8.8 3 16 3 C 19.9 3 23.4 4.7 25.8 7.4 Z"/>',
    'scripts': f'<circle cx="16" cy="16" r="13" fill="{GREEN}"/><path fill="#ffffff" d="M 13 9.5 Q 12 8.9 12 10.1 L 12 21.9 Q 12 23.1 13 22.5 L 22 17 Q 23.5 16 22 15 Z"/>',
    'family': f'<path fill="{GOLD}" d="M 16 2 L 28 6 L 27 17 C 26.5 23 22 27.2 16 30 C 10 27.2 5.5 23 5 17 L 4 6 Z"/><path fill="#fff3d8" fill-rule="evenodd" d="M 11 8 L 17 8 C 23 8 23.8 14 20 15.5 C 24.5 17 23.2 24 17 24 L 11 24 Z M 14 11 L 14 14.5 L 17 14.5 C 19.8 14.5 19.8 11 17 11 Z M 14 17.5 L 14 21 L 17.2 21 C 20.2 21 20.2 17.5 17.2 17.5 Z"/>',
    # Full helm: a broad visor and nose guard survive the smallest export.
    'gim': '<path fill="#b8bec7" d="M 5 25 L 5 14 C 5 7 9 3 16 3 C 23 3 27 7 27 14 L 27 25 L 20 29 L 16 26 L 12 29 Z"/><path fill="#858f9e" d="M 16 3 C 23 3 27 7 27 14 L 27 25 L 20 29 L 16 26 Z"/><path fill="#3fb96b" d="M 13 2 L 19 2 L 19 10 L 13 10 Z"/><path fill="#20262e" d="M 8 13 L 24 13 L 24 18 L 19 19 L 19 24 L 13 24 L 13 19 L 8 18 Z"/><path fill="#e6e8eb" d="M 14 12 L 18 12 L 18 25 L 16 27 L 14 25 Z"/>',
    'map': '<path fill="#3fb96b" d="M 3 7 L 11 4 L 21 7 L 29 4 L 29 25 L 21 28 L 11 25 L 3 28 Z"/><path fill="#2d8950" d="M 11 4 L 21 7 L 21 28 L 11 25 Z"/><path fill="#a5dfb8" d="M 10 4.4 L 12 4.3 L 12 25.3 L 10 25.4 Z M 20 7 L 22 6.6 L 22 27.6 L 20 27.7 Z"/><path fill="#e05a52" d="M 22 2 C 18.7 2 16 4.7 16 8 C 16 12 22 18 22 18 C 22 18 28 12 28 8 C 28 4.7 25.3 2 22 2 Z"/><circle cx="22" cy="8" r="2" fill="#fff0eb"/>',
    'clone': f'<circle cx="21" cy="9" r="5" fill="#a96900"/><path fill="#a96900" d="M 14 25 L 14 22 C 14 17.6 17.1 15 21 15 C 25.5 15 29 18 29 22 L 29 25 Z"/><circle cx="12" cy="13" r="5" fill="{GOLD}"/><path fill="{GOLD}" d="M 3 29 L 3 26 C 3 21.6 7 19 12 19 C 17 19 21 21.6 21 26 L 21 29 Z"/>',
    'bank': f'<path fill="#a96900" d="M 14 7 L 29 7 L 29 23 C 29 25 25.6 26 21.5 26 C 17.4 26 14 25 14 23 Z"/><ellipse cx="21.5" cy="7" rx="7.5" ry="3" fill="{GOLD}"/><path fill="#f1b642" d="M 16 12 Q 21.5 15 27 12 L 27 14 Q 21.5 17 16 14 Z M 16 18 Q 21.5 21 27 18 L 27 20 Q 21.5 23 16 20 Z"/><path fill="{GOLD}" d="M 3 17 L 18 17 L 18 26 C 18 28 14.6 29 10.5 29 C 6.4 29 3 28 3 26 Z"/><ellipse cx="10.5" cy="17" rx="7.5" ry="3" fill="#f1b642"/><path fill="#a96900" d="M 5 21 Q 10.5 24 16 21 L 16 23 Q 10.5 26 5 23 Z"/>',
    # Two separate busts above one chest communicate the shared group bank.
    'group-bank': '<circle cx="10" cy="5" r="3" fill="#b8bec7"/><circle cx="22" cy="5" r="3" fill="#b8bec7"/><path fill="#3fb96b" d="M 4 14 L 4 13 C 4 10 6 9 10 9 C 14 9 16 10 16 13 L 16 14 Z M 18 14 L 18 13 C 18 10 20 9 22 9 C 26 9 28 10 28 13 L 28 14 Z"/><rect x="3" y="17" width="26" height="12" rx="2" fill="#a96900"/><path fill="#e0a83a" d="M 3 21 L 3 19 Q 3 16 6 16 L 26 16 Q 29 16 29 19 L 29 21 Z"/><path fill="#f1b642" d="M 6 16 L 9 16 L 9 29 L 6 29 Z M 23 16 L 26 16 L 26 29 L 23 29 Z"/><rect x="13" y="20" width="6" height="5" rx="1" fill="#e6e8eb"/><rect x="15" y="21" width="2" height="3" fill="#30353e"/>',
    'open-client': '<rect x="3" y="5" width="26" height="19" rx="2" fill="#b8bec7"/><rect x="6" y="10" width="20" height="11" rx="0" fill="#30353e"/><rect x="6" y="7" width="3" height="1" rx="0" fill="#616975"/><path fill="#b8bec7" d="M 14 24 L 18 24 L 18 27 L 23 27 L 23 29 L 9 29 L 9 27 L 14 27 Z"/><path fill="#3fb96b" d="M 13 12 L 13 19 L 19 15.5 Z"/>',
    'output': '<path fill="#b8bec7" fill-rule="evenodd" d="M 3 4 L 29 4 L 29 28 L 3 28 Z M 6 10 L 6 25 L 26 25 L 26 10 Z"/><path fill="#3fb96b" d="M 8 13 L 11 13 L 16 18 L 11 23 L 8 23 L 13 18 Z"/><rect x="18" y="21" width="6" height="2" fill="#e6e8eb"/>',
    'character': '<path fill="#b8bec7" d="M 5 27 L 5 15 C 5 8 9 4 16 4 C 23 4 27 8 27 15 L 27 27 L 20 30 L 16 26 L 12 30 Z"/><path fill="#e0a83a" d="M 14 2 L 18 2 L 18 12 L 14 12 Z"/><path fill="#30353e" d="M 8 14 L 14 16 L 14 20 L 8 18 Z M 18 16 L 24 14 L 24 18 L 18 20 Z"/><path fill="#e6e8eb" d="M 15 14 L 17 14 L 17 25 L 15 25 Z"/>',
    'hiscores': '<path fill="#dc8a00" fill-rule="evenodd" d="M 2 6 L 30 6 L 30 11 C 30 17 25 20 21 20 L 11 20 C 7 20 2 17 2 11 Z M 5 9 L 5 11 C 5 15 8 17 11 17 L 21 17 C 24 17 27 15 27 11 L 27 9 Z"/><path fill="#e0a83a" d="M 8 3 L 24 3 L 23 14 Q 23 20 18 22 L 18 26 L 24 26 L 24 29 L 8 29 L 8 26 L 14 26 L 14 22 Q 9 20 9 14 Z"/><path fill="#fff3d8" d="M 16 6 L 17.5 10 L 22 10 L 18.5 13 L 20 17 L 16 14.5 L 12 17 L 13.5 13 L 10 10 L 14.5 10 Z"/>',
    'settings': '<path fill="#b8bec7" fill-rule="evenodd" d="M 12 2 L 20 2 L 21 6 L 23 7 L 27 6 L 31 13 L 28 16 L 28 18 L 31 21 L 27 28 L 23 27 L 21 28 L 20 31 L 12 31 L 11 28 L 9 27 L 5 28 L 1 21 L 4 18 L 4 16 L 1 13 L 5 6 L 9 7 L 11 6 Z M 16 10 C 12.4 10 10 12.6 10 16 C 10 19.4 12.4 22 16 22 C 19.6 22 22 19.4 22 16 C 22 12.6 19.6 10 16 10 Z"/>',
    'quests': '<path fill="#dc8a00" d="M 6 3 L 24 3 Q 28 3 28 7 L 28 10 L 10 10 L 10 25 Q 10 29 6 29 Q 2 29 2 25 L 2 22 L 6 22 Z"/><path fill="#e0a83a" d="M 10 3 L 24 3 Q 20 3 20 7 L 20 24 Q 20 29 15 29 L 6 29 Q 10 29 10 25 Z"/><path fill="#fff3d8" d="M 12 8 L 18 8 L 18 10 L 12 10 Z M 12 13 L 18 13 L 18 15 L 12 15 Z"/><path fill="#62a9df" d="M 23 12 L 25.5 17 L 31 18 L 27 22 L 28 28 L 23 25 L 18 28 L 19 22 L 15 18 L 20.5 17 Z"/>',
    'skills': '<path fill="#dc8a00" d="M 5 3 L 29 27 L 26 30 L 2 6 Z"/><path fill="#b8bec7" d="M 2 4 Q 14 0 23 9 L 28 17 L 20 12 Q 12 7 5 9 Z"/><path fill="#30353e" d="M 6 22 L 23 5 L 29 3 L 27 9 L 10 26 Z"/><path fill="#e6e8eb" d="M 8 22 L 24 6 L 28 4 L 26 8 L 10 24 Z"/><path fill="#e0a83a" d="M 4 18 L 14 28 L 12 30 L 2 20 Z"/><path fill="#dc8a00" d="M 6 23 L 9 26 L 5 30 L 2 27 Z"/>',
}


def contours(data):
    tokens = re.findall(r'[MLQCZ]|-?\d*\.?\d+', data)
    i, point, start, current, result = 0, (0, 0), (0, 0), [], []
    while i < len(tokens):
        command = tokens[i]
        i += 1
        if command == 'Z':
            current.append(start)
            result.append(current)
            current = []
            point = start
            continue
        count = {'M': 2, 'L': 2, 'Q': 4, 'C': 6}[command]
        values = list(map(float, tokens[i:i + count]))
        i += count
        end = tuple(values[-2:])
        if command == 'M':
            if current:
                result.append(current)
            current, start = [end], end
        elif command == 'L':
            current.append(end)
        else:
            x, y = point
            for step in range(1, 65):
                t = step / 64
                u = 1 - t
                if command == 'Q':
                    a, b, c, d = values
                    current.append((u*u*x + 2*u*t*a + t*t*c,
                                    u*u*y + 2*u*t*b + t*t*d))
                else:
                    a, b, c, d, e, f = values
                    current.append((u**3*x + 3*u*u*t*a + 3*u*t*t*c + t**3*e,
                                    u**3*y + 3*u*u*t*b + 3*u*t*t*d + t**3*f))
        point = end
    if current:
        result.append(current)
    return result


def raster(svg, size):
    scale = size * 8 / 32
    canvas = Image.new('RGBA', (size * 8, size * 8))
    for element in ET.fromstring(svg):
        tag = element.tag.split('}')[-1]
        if tag in ('title', 'desc'):
            continue
        mask = Image.new('L', canvas.size)
        draw = ImageDraw.Draw(mask)
        def value(name, default=0):
            return float(element.get(name, default)) * scale
        if tag == 'path':
            for index, contour in enumerate(contours(element.get('d'))):
                # Even-odd sources use later contours as transparent counters.
                fill = 0 if element.get('fill-rule') == 'evenodd' and index else 255
                draw.polygon([(x * scale, y * scale) for x, y in contour], fill=fill)
        elif tag == 'rect':
            x, y, w, h = (value(k) for k in ('x', 'y', 'width', 'height'))
            draw.rounded_rectangle((x, y, x+w-1, y+h-1), radius=value('rx'), fill=255)
        elif tag in ('circle', 'ellipse'):
            x, y = value('cx'), value('cy')
            rx = value('r') if tag == 'circle' else value('rx')
            ry = value('r') if tag == 'circle' else value('ry')
            draw.ellipse((x-rx, y-ry, x+rx-1, y+ry-1), fill=255)
        else:
            raise ValueError(tag)
        layer = Image.new('RGBA', canvas.size, element.get('fill'))
        layer.putalpha(mask)
        canvas = Image.alpha_composite(canvas, layer)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main():
    for name, shapes in SOURCES.items():
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" '
               f'viewBox="0 0 32 32" role="img" aria-labelledby="title">\n'
               f'  <title id="title">Bot Scape {name.replace("-", " ")}</title>\n'
               f'  {shapes}\n</svg>\n')
        (ROOT / f'{name}.svg').write_text(svg, encoding='utf-8')
        for size in (16, 24, 32):
            raster(svg, size).save(ROOT / f'{name}-{size}.png', optimize=True)
    # Keep a reproducible, native-size comparison on the launcher backgrounds.
    backgrounds = ('#161a20', '#0f1115', '#1e1e1e')
    sheet = Image.new('RGB', (960, 70 + len(SOURCES) * 52))
    draw = ImageDraw.Draw(sheet)
    for column, background in enumerate(backgrounds):
        left = column * 320
        draw.rectangle((left, 0, left + 319, sheet.height), fill=background)
        draw.text((left + 16, 12), background, fill='#b8bec7')
        for size, x in zip((16, 24, 32), (136, 204, 272)):
            draw.text((left + x - 8, 36), str(size), fill='#b8bec7')
        for row, name in enumerate(SOURCES):
            y = 82 + row * 52
            draw.text((left + 12, y - 6), name, fill='#e6e8eb')
            for size, x in zip((16, 24, 32), (136, 204, 272)):
                with Image.open(ROOT / f'{name}-{size}.png') as icon:
                    sheet.paste(icon, (left + x - size // 2, y - size // 2), icon)
    sheet.save(ROOT / 'contact-sheet.png', optimize=True)
    print(f'Generated {len(SOURCES)} SVG sources, {len(SOURCES) * 3} transparent PNGs and contact sheet.')


if __name__ == '__main__':
    main()
