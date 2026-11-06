"""Rebuild Bot Scape brand/UI assets. Requires Pillow and fontTools.

Run: python assets/brand/generate.py
SVGs use portable outlined lettering; no installed fonts are needed to display.
The small renderer samples the same SVG paths at 4x for transparent PNGs.
"""
from pathlib import Path
import math
import re
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen

BRAND = Path(__file__).resolve().parent
UI = BRAND.parent / 'ui'
GOLD, GREEN, MUTED = '#e0a83a', '#3fb96b', '#8b919c'
DARK, PANEL, CARD, BORDER = '#0f1115', '#161a20', '#1d222a', '#2a313b'


def svg(w, h, title, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" role="img" aria-labelledby="title">\n'
            f'  <title id="title">{title}</title>\n{body}\n</svg>\n')


def path(d, fill='none', stroke=None, width=2):
    extra = f' stroke="{stroke}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"' if stroke else ''
    return f'  <path d="{d}" fill="{fill}" fill-rule="evenodd"{extra}/>'


def rect(x, y, w, h, fill, r=0, stroke=None, width=2):
    extra = f' stroke="{stroke}" stroke-width="{width}"' if stroke else ''
    return f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}"{extra}/>'


def circle(x, y, r, fill, stroke=None, width=2):
    extra = f' stroke="{stroke}" stroke-width="{width}"' if stroke else ''
    return f'  <circle cx="{x}" cy="{y}" r="{r}" fill="{fill}"{extra}/>'


def contours(data):
    tokens = re.findall(r'[MLQCZ]|-?\d*\.?\d+(?:[eE][-+]?\d+)?', data)
    i, point, start, points, out = 0, (0, 0), (0, 0), [], []
    while i < len(tokens):
        op = tokens[i]
        i += 1
        if op == 'Z':
            points.append(start)
            out.append((points, True))
            points, point = [], start
            continue
        n = {'M': 2, 'L': 2, 'Q': 4, 'C': 6}[op]
        v = list(map(float, tokens[i:i+n]))
        i += n
        end = tuple(v[-2:])
        if op == 'M':
            if points:
                out.append((points, False))
            points, start = [end], end
        elif op == 'L':
            points.append(end)
        else:
            x, y = point
            for j in range(1, 33):
                t, u = j / 32, 1 - j / 32
                if op == 'Q':
                    a, b, c, d = v
                    points.append((u*u*x+2*u*t*a+t*t*c, u*u*y+2*u*t*b+t*t*d))
                else:
                    a, b, c, d, e, f = v
                    points.append((u**3*x+3*u*u*t*a+3*u*t*t*c+t**3*e,
                                   u**3*y+3*u*u*t*b+3*u*t*t*d+t**3*f))
        point = end
    if points:
        out.append((points, False))
    return out


def render(source, size):
    """Render the deliberately small SVG vocabulary used in this asset set."""
    root = ET.fromstring(source)
    vw, vh = map(float, root.get('viewBox').split()[2:])
    ss = 4
    canvas = Image.new('RGBA', (size[0]*ss, size[1]*ss))
    sx, sy = size[0]*ss/vw, size[1]*ss/vh

    def visit(el, tr=(1, 1, 0, 0)):
        nonlocal canvas
        tag = el.tag.split('}')[-1]
        if tag in ('title', 'defs', 'desc'):
            return
        a, b, tx, ty = tr
        if el.get('transform'):
            nums = list(map(float, re.findall(r'-?\d*\.?\d+', el.get('transform'))))
            aa, _, _, bb, xx, yy = nums
            a, b, tx, ty = a*aa, b*bb, tx+a*xx, ty+b*yy
        if tag in ('svg', 'g'):
            for child in el:
                visit(child, (a, b, tx, ty))
            return
        def val(k, default=0):
            return float(el.get(k, default))
        if tag == 'path':
            parts = contours(el.get('d'))
        elif tag == 'rect':
            x, y, w, h, r = [val(k) for k in ('x', 'y', 'width', 'height', 'rx')]
            pts = []
            for cx, cy, base in [(x+w-r,y+r,-90), (x+w-r,y+h-r,0), (x+r,y+h-r,90), (x+r,y+r,180)]:
                for j in range(13):
                    angle = math.radians(base + j*90/12)
                    pts.append((cx+r*math.cos(angle), cy+r*math.sin(angle)))
            parts = [(pts+[pts[0]], True)]
        elif tag == 'circle':
            x, y, r = [val(k) for k in ('cx', 'cy', 'r')]
            pts = [(x+r*math.cos(j*math.tau/96),y+r*math.sin(j*math.tau/96)) for j in range(97)]
            parts = [(pts, True)]
        else:
            raise ValueError(tag)
        mapped = [([(int(round((x*a+tx)*sx)),int(round((y*b+ty)*sy))) for x,y in pts], closed) for pts,closed in parts]
        fill = el.get('fill', 'none')
        if fill == 'url(#glow)':
            # The hero's SVG radial gradient, evaluated before supersampling.
            layer = Image.new('RGBA', size)
            pixels = layer.load()
            for y in range(size[1]):
                for x in range(size[0]):
                    t = min(1, math.hypot((x/size[0]-.76)/.48, (y/size[1]-.5)/1.25))
                    # Three SVG stops: warm horizon / dusk / page black.
                    if t < .5:
                        u, c1, c2 = t*2, (60,47,29), (27,28,29)
                    else:
                        u, c1, c2 = (t-.5)*2, (27,28,29), (15,17,21)
                    pixels[x,y] = (*[round(v*(1-u)+w*u) for v,w in zip(c1,c2)],255)
            canvas.alpha_composite(layer.resize(canvas.size, Image.Resampling.BICUBIC))
            return
        if fill != 'none':
            # XOR subpaths implements evenodd counters, including outlined text.
            from PIL import ImageChops
            mask = Image.new('1', canvas.size)
            for pts, _ in mapped:
                sub = Image.new('1', canvas.size)
                ImageDraw.Draw(sub).polygon(pts, fill=1)
                mask = ImageChops.logical_xor(mask, sub)
            layer = Image.new('RGBA', canvas.size, fill)
            layer.putalpha(mask.convert('L'))
            canvas.alpha_composite(layer)
        if el.get('stroke'):
            draw = ImageDraw.Draw(canvas)
            width = max(1, round(val('stroke-width', 2)*abs(a)*sx))
            for pts, _ in mapped:
                draw.line(pts, fill=el.get('stroke'), width=width, joint='curve')
                if el.get('stroke-linecap') == 'round':
                    r = width/2
                    for x,y in (pts[0],pts[-1]):
                        draw.ellipse((x-r,y-r,x+r,y+r), fill=el.get('stroke'))
    visit(root)
    return canvas.resize(size, Image.Resampling.LANCZOS)


def save(folder, name, w, h, title, body, png_size=None):
    source = svg(w, h, title, body)
    (folder/f'{name}.svg').write_text(source, encoding='utf-8')
    if png_size:
        render(source, png_size).save(folder/f'{name}.png', optimize=True)
    return source


def emblem(simple=False):
    pieces = [path('M 128 12 L 230 48 L 222 148 Q 213 207 128 246 Q 43 207 34 148 L 26 48 Z', GOLD),
              path('M 128 29 L 213 59 L 206 146 Q 198 192 128 228 Q 58 192 50 146 L 43 59 Z', PANEL)]
    if not simple:
        pieces += [path('M 128 38 L 203 65 L 197 145 Q 189 184 128 218 Q 67 184 59 145 L 53 65 Z', 'none', '#765d32', 3),
                   path('M 73 56 L 128 37 L 183 56', 'none', GOLD, 3)]
    pieces += [path('M 128 68 L 128 85', 'none', GOLD, 9), circle(128, 64, 9, GOLD),
               rect(63, 110, 12, 34, GOLD, 5), rect(181, 110, 12, 34, GOLD, 5),
               rect(76, 88, 104, 85, GOLD, 20),
               rect(88, 102, 80, 45, DARK, 12),
               rect(101, 114, 13, 18, GREEN, 5), rect(142, 114, 13, 18, GREEN, 5)]
    if not simple:
        pieces += [path('M 112 158 L 144 158', 'none', PANEL, 5),
                   path('M 115 192 L 128 203 L 141 192', 'none', GOLD, 5)]
    return '\n'.join(pieces)


def hub_emblem():
    """A dashboard silhouette, deliberately different from the client's shield.

    Coordinates follow a 16px grid: 1px frame/gutters and solid 4px tiles.
    The same geometry works at every export size, including 16px.
    """
    return '\n'.join([
        rect(16, 16, 224, 224, GOLD, 40),
        rect(32, 32, 192, 192, PANEL, 24),
        rect(48, 48, 64, 64, GOLD, 8),
        rect(128, 48, 80, 64, GOLD, 8),
        rect(48, 128, 64, 80, GOLD, 8),
        path('M 136 128 L 208 168 L 136 208 Z', GREEN),
    ])


def hub_assets():
    source = save(BRAND, 'hub', 256, 256, 'Bot Scape hub dashboard', hub_emblem())
    frames = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        frame = render(source, (size, size))
        frame.save(BRAND/f'hub-{size}.png', optimize=True)
        frames.append(frame)
    frames[-1].save(BRAND/'hub.ico', format='ICO', sizes=[im.size for im in frames],
                    append_images=frames[:-1])
    hub_contact_sheet()


def hub_contact_sheet():
    """Actual ICO frames at native size on dark and light Windows taskbars."""
    sheet = Image.new('RGB', (960, 480), DARK)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 16)
    draw.text((24, 16), 'Before: hub + client                 After: hub + client (shield unchanged)',
              font=font, fill='#e6e8eb')
    client, hub = Image.open(BRAND/'app.ico'), Image.open(BRAND/'hub.ico')
    for row, bg in enumerate((PANEL, '#eeeeee')):
        top = 54 + row*164
        draw.rounded_rectangle((16, top, 944, top+148), radius=12, fill=bg)
        ink = MUTED if row == 0 else '#444444'
        for col, size in enumerate((16, 24, 32, 48)):
            x = 40 + col*224
            draw.text((x, top+12), f'{size} px', font=font, fill=ink)
            for offset, ico in ((0, client), (56, client), (112, hub), (168, client)):
                image = ico.ico.getimage((size, size)).convert('RGBA')
                sheet.paste(image, (x+offset+(48-size)//2, top+58+(48-size)//2), image)
            draw.text((x, top+116), 'Before          After', font=font, fill=ink)
    draw.text((24, 406), 'Gold dashboard + green play: hub. Gold robot shield: game client.',
              font=font, fill='#e6e8eb')
    sheet.save(BRAND/'hub-comparison.png', optimize=True)


class OutlinePen(BasePen):
    def __init__(self, glyphset):
        super().__init__(glyphset)
        self.commands = []
    def emit(self, op, *pts):
        self.commands.append(op + ' ' + ' '.join(f'{v:.2f}'.rstrip('0').rstrip('.') for pt in pts for v in pt))
    def _moveTo(self,p): self.emit('M',p)
    def _lineTo(self,p): self.emit('L',p)
    def _curveToOne(self,a,b,c): self.emit('C',a,b,c)
    def _qCurveToOne(self,a,b): self.emit('Q',a,b)
    def _closePath(self): self.commands.append('Z')
    def _endPath(self): pass


def wordmark():
    font = TTFont('C:/Windows/Fonts/georgiab.ttf')
    glyphs, cmap = font.getGlyphSet(), font.getBestCmap()
    scale, x, body = 0.046, 4, []
    for char in 'BOT SCAPE':
        if char == ' ':
            x += 23
            continue
        name = cmap[ord(char)]
        pen = OutlinePen(glyphs)
        glyphs[name].draw(pen)
        body.append(f'  <g transform="matrix({scale} 0 0 -{scale} {x:.2f} 82)">\n{path(" ".join(pen.commands), GOLD)}\n  </g>')
        x += glyphs[name].width*scale + 6
    return round(x), '\n'.join(body)


def empties():
    base = path('M 37 137 L 203 137', 'none', BORDER, 2)
    scripts = [base, rect(76,31,88,100,PANEL,9,MUTED,2.5),
               path('M 91 48 L 116 48 M 91 56 L 106 56', 'none', BORDER,3),
               path('M 103 72 L 94 81 L 103 90 M 137 72 L 146 81 L 137 90 M 124 70 L 116 93','none',GREEN,3),
               path('M 98 111 L 141 111', 'none',BORDER,3), circle(170,113,18,PANEL,GREEN,2.5),
               path('M 170 106 L 170 120 M 163 113 L 177 113','none',GREEN,2.5)]
    offline = [base, rect(70,48,100,77,PANEL,10,MUTED,2.5),
               path('M 70 86 L 170 86 M 84 64 L 123 64 M 84 102 L 114 102','none',BORDER,3),
               circle(153,65,3,MUTED), circle(153,103,3,MUTED),
               path('M 91 30 Q 120 8 149 30 M 101 38 Q 120 24 139 38','none',MUTED,2.5),
               circle(172,119,17,PANEL,GOLD,2.5), path('M 166 119 L 178 119','none',GOLD,2.5)]
    bank = [base, path('M 62 77 L 77 47 L 163 47 L 178 77 L 178 129 L 62 129 Z',PANEL,MUTED,2.5),
            path('M 62 77 L 178 77 M 78 48 L 91 77 M 161 48 L 149 77 M 81 94 L 81 119 M 159 94 L 159 119','none',BORDER,2.5),
            rect(110,69,20,25,PANEL,4,GOLD,2.5),circle(120,81,2,GOLD),
            path('M 106 111 Q 120 101 134 111','none',GOLD,2.5),
            path('M 193 52 L 193 64 M 187 58 L 199 58 M 47 93 L 47 101 M 43 97 L 51 97','none',GOLD,2)]
    team = [base, circle(80,55,19,PANEL,MUTED,2.5),
            path('M 46 126 L 46 112 Q 46 83 80 83 Q 114 83 114 112 L 114 126','none',MUTED,2.5),
            circle(155,55,19,PANEL,GOLD,2.5),
            path('M 121 126 L 121 112 Q 121 83 155 83 Q 189 83 189 112 L 189 126','none',GOLD,2.5),
            path('M 148 55 L 162 55 M 155 48 L 155 62','none',GOLD,2.5),
            path('M 106 33 L 117 26 L 128 33','none',BORDER,2)]
    for name, body in [('scripts',scripts),('offline',offline),('bank',bank),('team',team)]:
        save(UI, f'empty-{name}',240,160,f'Bot Scape: {name} empty state','\n'.join(body).replace(BORDER,MUTED),(240,160))


def categories():
    # Distinct muted backgrounds; semantic action colours stay in the UI.
    data = {
        'skilling': ('#223b32','#86bd98','M 11 23 L 21 10 M 10 10 Q 17 5 24 13 M 10 10 L 9 14'),
        'combat': ('#402c30','#d79a9a','M 10 22 L 21 11 L 24 8 L 23 14 L 12 25 M 8 19 L 14 25 M 10 23 L 8 25'),
        'questing': ('#323047','#b2a4d5','M 11 8 L 23 8 L 21 12 L 23 16 L 11 16 Z M 11 8 L 11 25'),
        'money': ('#403622','#d8b66e','M 8 12 C 8 8 24 8 24 12 C 24 16 8 16 8 12 Z M 8 12 L 8 21 C 8 25 24 25 24 21 L 24 12 M 8 17 C 8 21 24 21 24 17'),
        'utility': ('#293944','#93b4ca','M 12 8 L 12 24 M 21 8 L 21 24 M 8 12 L 16 12 M 17 20 L 25 20'),
        'team': ('#3b3040','#c3a0ca','M 8 24 L 8 22 Q 8 17 13 17 Q 18 17 18 22 L 18 24 M 20 17 Q 25 17 25 22 L 25 24'),
    }
    for name, (bg, ink, glyph) in data.items():
        body = [rect(0,0,32,32,bg,8),path(glyph,'none',ink,1.8)]
        if name == 'team':
            body += [circle(13,11,3,'none',ink,1.8),circle(22,11,3,'none',ink,1.8)]
        save(UI/'categories',name,32,32,f'Bot Scape {name} category','\n'.join(body),(32,32))


def hero():
    body = ['''  <defs>
    <radialGradient id="glow" cx="76%" cy="50%" r="48%" gradientTransform="matrix(1 0 0 2.60417 0 -0.802085)">
      <stop stop-color="#3c2f1d"/>
      <stop offset=".5" stop-color="#1b1c1d"/>
      <stop offset="1" stop-color="#0f1115"/>
    </radialGradient>
  </defs>''', rect(0,0,1600,500,'url(#glow)'),
        circle(1240,134,44,'#54432a'),circle(1251,124,42,'#322b21'),
        path('M 0 455 Q 210 441 420 345 L 610 256 L 704 290 L 842 207 L 1011 292 L 1130 241 L 1282 284 L 1412 222 L 1600 303 L 1600 500 L 0 500 Z','#202326'),
        path('M 0 479 Q 300 460 530 392 Q 697 269 841 334 Q 1008 234 1160 334 Q 1390 259 1600 337 L 1600 500 L 0 500 Z','#191e23'),
        # Castle silhouette and a few gold windows, all on the right.
        path('M 1030 321 L 1030 221 L 1024 221 L 1047 194 L 1070 221 L 1064 221 L 1064 253 L 1110 253 L 1110 205 L 1104 205 L 1133 171 L 1162 205 L 1156 205 L 1156 246 L 1174 246 L 1174 236 L 1185 236 L 1185 246 L 1196 246 L 1196 236 L 1207 236 L 1207 246 L 1218 246 L 1218 216 L 1212 216 L 1234 190 L 1256 216 L 1250 216 L 1250 321 Z','#10151a'),
        rect(1043,235,7,12,'#806133',3),rect(1128,219,8,16,'#a17a3c',4),rect(1230,232,7,12,'#806133',3),
        path('M 1120 321 L 1120 284 Q 1133 264 1146 284 L 1146 321 Z','#272821'),
        path('M 0 430 Q 172 404 327 431 Q 494 455 650 394 Q 828 325 1020 377 Q 1180 329 1340 363 Q 1460 297 1600 337 L 1600 500 L 0 500 Z','#11171b'),
        # Mine mouth, timber frame, rails and a warm lamp.
        path('M 1326 411 L 1326 374 Q 1366 318 1406 374 L 1406 411 Z','#090d11'),
        path('M 1328 410 L 1333 363 L 1397 363 L 1403 410 M 1329 375 L 1401 375','none','#4c4130',6),
        path('M 1351 409 L 1310 476 M 1383 409 L 1401 476 M 1336 435 L 1389 435 M 1324 454 L 1395 454 M 1311 475 L 1402 475','none','#30302b',3),
        circle(1417,375,5,GOLD),path('M 1417 358 L 1417 369','none','#655033',2),
        path('M 885 379 L 908 341 L 930 379 Z M 894 356 L 908 331 L 923 356 Z M 955 375 L 974 344 L 993 375 Z M 966 353 L 974 336 L 984 353 Z M 1490 348 L 1512 310 L 1534 348 Z M 1499 324 L 1512 299 L 1526 324 Z','#10151a'),
        path('M 0 468 Q 250 443 476 470 Q 711 423 924 464 Q 1118 420 1294 463 L 1269 500 L 0 500 Z','#0f1115')]
    source = save(UI,'hero',1600,500,'Bot Scape: quiet hills, castle and mine at dusk','\n'.join(body))
    # Opaque RGB is smaller and appropriate for a background banner.
    render(source,(1600,500)).convert('RGB').save(UI/'hero.png',optimize=True)


def contact_sheet():
    sheet = Image.new('RGB',(1200,1050),DARK)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',18)
    def paste(file,x,y):
        image = Image.open(file).convert('RGBA')
        sheet.paste(image,(x,y),image)
    paste(BRAND/'logo-256.png',35,20)
    paste(BRAND/'wordmark.png',340,45)
    paste(BRAND/'lockup-600.png',320,160)
    paste(BRAND/'logo-64.png',980,60)
    ico = Image.open(BRAND/'app.ico')
    for j,size in enumerate((16,24,32,48)):
        image = ico.ico.getimage((size,size)).convert('RGBA')
        sheet.paste(image,(980,160+j*55),image)
        draw.text((1040,160+j*55),str(size),font=font,fill=MUTED)
    for j,name in enumerate(('scripts','offline','bank','team')):
        paste(UI/f'empty-{name}.png',20+j*295,355)
        draw.text((70+j*295,520),name,font=font,fill=MUTED)
    for j,name in enumerate(('skilling','combat','questing','money','utility','team')):
        paste(UI/'categories'/f'{name}.png',40+j*192,585)
        draw.text((82+j*192,587),name,font=font,fill=MUTED)
    sheet.paste(Image.open(UI/'hero.png').resize((1200,375)),(0,675))
    draw.text((60,760),'Your world. Your bots.',font=ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf',42),fill='#e6e8eb')
    sheet.save(BRAND/'contact-sheet.png',optimize=True)


def main():
    BRAND.mkdir(parents=True,exist_ok=True)
    (UI/'categories').mkdir(parents=True,exist_ok=True)
    source = save(BRAND,'logo',256,256,'Bot Scape robot shield',emblem())
    for size in (512,256,128,64):
        render(source,(size,size)).save(BRAND/f'logo-{size}.png',optimize=True)
    frames = []
    for size in (16,24,32,48,64,128,256):
        src = svg(256,256,'Bot Scape',emblem(size <= 24))
        frames.append(render(src,(size,size)))
    frames[-1].save(BRAND/'app.ico',format='ICO',sizes=[im.size for im in frames],append_images=frames[:-1])
    hub_assets()
    width, lettering = wordmark()
    save(BRAND,'wordmark',width,104,'BOT SCAPE',lettering,(width,104))
    factor = (440/width)
    lockup = (f'<g transform="matrix(.5625 0 0 .5625 0 0)">\n{emblem()}\n</g>\n'
              f'<g transform="matrix({factor} 0 0 {factor} 158 {72-factor*48.5:.3f})">\n{lettering}\n</g>')
    src = save(BRAND,'lockup',600,144,'Bot Scape horizontal logo',lockup)
    render(src,(600,144)).save(BRAND/'lockup-600.png',optimize=True)
    empties()
    categories()
    hero()
    contact_sheet()
    print('Built client and hub icons, hub comparison, wordmark, lockup, empty states, badges and hero.')


if __name__ == '__main__':
    main()
