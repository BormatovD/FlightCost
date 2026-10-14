"""Монтаж видеоинструкции из съёмки capture.py.

    python3 montage.py take/ out.mp4 [--stills]

Читает take/log.json и кадры, сценарий берёт по пути из лога (заставка,
концовка). Шортс 1080×1920, 30 кадров/с: сверху номер шага и подпись,
посередине экран телефона, касания кольцами, приближения внутри экрана,
долгие ожидания ускорены с пометкой.
"""
import bisect, json, re, math, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.environ.get("FCA_FONTS", os.path.join(HERE, "fonts"))

BG = (11, 13, 16)
FG = (236, 240, 244)
MUTED = (128, 138, 150)
SKY, AQUA, BLUE, GREEN, DEEP = (0, 169, 237), (0, 237, 229), (0, 95, 237), (0, 237, 148), (0, 20, 237)
ORANGE = (255, 138, 42)

INTRO, OUTRO, XF = 3.2, 4.2, 0.6         # с; XF — перекрытие переходов

CARD_W = 800
CARD_X = (W - CARD_W) // 2
CARD_Y = 330
RADIUS = 46


PLEX = "https://raw.githubusercontent.com/IBM/plex/master/packages/{p}/fonts/complete/ttf/{f}"


def ensure_fonts():
    """IBM Plex — шрифт витрины; TTF кладутся в FCA_FONTS или рядом со скриптом"""
    import urllib.request
    os.makedirs(FONTS, exist_ok=True)
    need = [("plex-sans", f"IBMPlexSans-{w}.ttf") for w in ("Regular", "Medium", "SemiBold", "Bold")] + \
           [("plex-mono", "IBMPlexMono-Medium.ttf")]
    for pkg, f in need:
        dst = os.path.join(FONTS, f)
        if not os.path.exists(dst):
            print("шрифт", f)
            urllib.request.urlretrieve(PLEX.format(p=pkg, f=f), dst)


def font(w, s): return ImageFont.truetype(os.path.join(FONTS, f"IBMPlexSans-{w}.ttf"), s)
def mono(s): return ImageFont.truetype(os.path.join(FONTS, "IBMPlexMono-Medium.ttf"), s)


def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ease(x): x = clamp(x); return 1 - (1 - x) ** 3
def ease2(x): x = clamp(x); return 3 * x * x - 2 * x ** 3
def ramp(t, t0, t1): return ease((t - t0) / (t1 - t0)) if t1 > t0 else float(t >= t0)
def mix(c, a, base=BG): return tuple(int(base[i] + (c[i] - base[i]) * a) for i in range(3))


def text(d, xy, s, f, col, a=1.0, anchor="la"):
    if a > 0.01:
        d.text(xy, s, font=f, fill=mix(col, a), anchor=anchor)


class Take:
    def __init__(self, path):
        self.path = path
        lg = json.load(open(os.path.join(path, "log.json"), encoding="utf-8"))
        self.vw, self.vh, self.dpr = lg["viewport"]
        self.ft = lg["frames"]
        self.ev = lg["events"]
        sp = lg.get("scenario", "")
        cand = [sp, os.path.join(os.path.dirname(path.rstrip("/")), os.path.basename(sp)),
                os.path.join(HERE, os.path.basename(sp))]
        self.sc = next((json.load(open(c, encoding="utf-8")) for c in cand if c and os.path.exists(c)), {})
        self.watch = lg.get("watch", [])
        self.reads = lg.get("reads", [])
        # моменты, когда значение на табло сменилось: (время, прежнее)
        self.changes = [[] for _ in self.watch]
        for k in range(1, len(self.reads)):
            for j in range(len(self.watch)):
                if self.reads[k][j] != self.reads[k - 1][j] and self.reads[k][j] and self.reads[k - 1][j]:
                    self.changes[j].append((self.ft[k], self.reads[k - 1][j]))
        self.end = next((e["t"] for e in self.ev if e["kind"] == "end"), self.ft[-1])
        self.start = next((e["t"] for e in self.ev if e["kind"] == "start"), 0.0)
        # ускоренные промежутки: виртуальное время → время ролика
        self.fast = []
        on = None
        for e in self.ev:
            if e["kind"] == "fast_on": on = e
            if e["kind"] == "fast_off" and on:
                self.fast.append((on["t"], e["t"], on.get("x", 6))); on = None
        self.dur = self.to_video(self.end)
        self._cache = (None, None)

    def to_video(self, v):
        out = v - self.start
        for a, b, x in self.fast:
            if v > a:
                span = min(v, b) - a
                out -= span - span / x
        return out

    def to_virtual(self, t):
        v = self.start + t
        for a, b, x in self.fast:
            va = self.to_video(a)
            if t <= va: break
            vb_video = self.to_video(b)
            if t < vb_video:
                return a + (t - va) * x
            v = b + (t - vb_video)
        return v

    def fast_at(self, v):
        return next((x for a, b, x in self.fast if a <= v < b), None)

    def frame(self, v):
        k = max(0, bisect.bisect_right(self.ft, v) - 1)
        if self._cache[0] != k:
            self._cache = (k, Image.open(os.path.join(self.path, "frames", f"{k:05d}.jpg")).convert("RGB"))
        return self._cache[1]

    def readout(self, v):
        if not self.reads: return None
        k = max(0, bisect.bisect_right(self.ft, v) - 1)
        return self.reads[k]

    def caption(self, v):
        caps = [e for e in self.ev if e["kind"] == "caption" and e["t"] <= v]
        return caps[-1] if caps else None

    def zoom(self, v):
        """(scale, cx, cy) в css-пикселях экрана с плавным входом и выходом"""
        s, cx, cy = 1.0, self.vw / 2, self.vh / 2
        for e in self.ev:
            if e["kind"] != "zoom": continue
            t0, t1 = e["t"], e["t"] + e["ms"] / 1000
            if t0 - 0.05 <= v <= t1 + 0.6:
                k = min(ease2((v - t0) / 0.55), 1 - ease2((v - (t1 - 0.1)) / 0.6))
                x, y, w, h = e["box"]
                s = 1 + (e["scale"] - 1) * k
                cx = self.vw / 2 + (x + w / 2 - self.vw / 2) * k
                cy = self.vh / 2 + (y + h / 2 - self.vh / 2) * k
        return s, cx, cy


def rounded_mask(w, h, r):
    m = Image.new("L", (w * 2, h * 2), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * 2 - 1, h * 2 - 1), r * 2, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def build(take, out, stills=None):
    sc = take.sc
    intro = sc.get("intro", {"title": ["flightcost.app"], "sub": ""})
    outro = sc.get("outro", {"title": ["flightcost.app"], "url": "flightcost.app", "sub": ""})
    card_h = round(CARD_W * take.vh / take.vw)
    k_css = CARD_W / take.vw                       # css px → px карточки
    mask = rounded_mask(CARD_W, card_h, RADIUS)
    shadow = Image.new("RGBA", (CARD_W + 160, card_h + 160), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((80, 80, 80 + CARD_W, 80 + card_h), RADIUS, fill=(0, 169, 237, 60))
    shadow = shadow.filter(ImageFilter.GaussianBlur(38))

    T_SHOW0 = INTRO - XF                           # экран въезжает
    T_SHOW1 = T_SHOW0 + take.dur                   # экран уходит
    total = T_SHOW1 + OUTRO - XF + XF
    taps = [e for e in take.ev if e["kind"] == "tap"]
    drags = [e for e in take.ev if e["kind"] == "drag"]
    f_cap, f_sub, f_num = font("SemiBold", 60), font("Regular", 36), font("Bold", 46)

    def screen_at(tv):
        v = take.to_virtual(clamp(tv, 0, take.dur))
        src = take.frame(v)
        s, cx, cy = take.zoom(v)
        # окно в исходном кадре (в пикселях кадра) под приближение
        sw, sh = src.size
        px = sw / take.vw
        win_w, win_h = sw / s, sh / s
        x0 = clamp(cx * px - win_w / 2, 0, sw - win_w)
        y0 = clamp(cy * px - win_h / 2, 0, sh - win_h)
        img = src.crop((round(x0), round(y0), round(x0 + win_w), round(y0 + win_h))).resize(
            (CARD_W, card_h), Image.LANCZOS)
        to_card = lambda X, Y: ((X * px - x0) / win_w * CARD_W, (Y * px - y0) / win_h * card_h)
        return img, v, s, to_card

    def num(x):
        m = re.search(r"[−-]?\d[\d\s\u00a0\u202f,.]*", x or "")
        if not m: return None
        z = re.sub(r"[\s\u00a0\u202f]", "", m.group(0)).replace("−", "-")
        z = z.replace(",", ".") if z.count(",") == 1 and len(z.split(",")[1]) <= 2 else z.replace(",", "")
        try: return float(z)
        except ValueError: return None

    def draw_readout(d, v, y0, a):
        vals = take.readout(v) or []
        n = len(take.watch)
        x0, x1, h = CARD_X, CARD_X + CARD_W, 122
        d.rounded_rectangle((x0, y0, x1, y0 + h), 26, fill=mix((22, 26, 33), a))
        cw = (x1 - x0) / n
        for j, w in enumerate(take.watch):
            cx = x0 + cw * j + 26
            val = vals[j] if j < len(vals) else ""
            col = FG
            if w.get("kind") == "signed" and val:
                col = ORANGE if val.strip()[:1] in "−-" else GREEN
            # вспышка и разница после смены значения
            last = [c for c in take.changes[j] if c[0] <= v]
            flash = 0.0
            if last:
                tch, prev = last[-1]
                flash = 1 - clamp((v - tch) / 1.6)
                a0, a1 = num(prev), num(val)
                if flash > 0 and a0 is not None and a1 is not None and abs(a1 - a0) > 1e-9:
                    dlt = a1 - a0
                    s_ = f"{abs(dlt):,.1f}".replace(",", " ").removesuffix(".0").replace(".", ",")
                    good = (dlt > 0) == (w.get("kind") == "signed")
                    fa = a * min(1, flash * 2.5)
                    f_ = font("SemiBold", 30)
                    tw = d.textlength(s_, font=f_) + 26          # 26 — треугольник и зазор
                    mx = x0 + cw * j + cw / 2
                    rise = (1 - flash) * 10
                    yc = y0 - 32 - rise
                    c_ = GREEN if good else ORANGE
                    d.rounded_rectangle((mx - tw / 2 - 18, yc - 22, mx + tw / 2 + 18, yc + 22), 22,
                                        fill=mix((22, 26, 33), fa))
                    tx = mx - tw / 2
                    tri = [(tx, yc + 7), (tx + 16, yc + 7), (tx + 8, yc - 7)] if dlt > 0 else \
                          [(tx, yc - 7), (tx + 16, yc - 7), (tx + 8, yc + 7)]
                    d.polygon(tri, fill=mix(c_, fa))
                    text(d, (tx + 26, yc), s_, f_, c_, fa, "lm")
            if flash > 0:
                col = tuple(int(col[i] + (AQUA[i] - col[i]) * flash) for i in range(3))
            text(d, (cx, y0 + 22), w["label"], font("Regular", 26), MUTED, a)
            text(d, (cx, y0 + 58), val, font("Bold", 44), col, a)
            if j:
                d.line((x0 + cw * j, y0 + 22, x0 + cw * j, y0 + h - 22), fill=mix((52, 58, 66), a), width=2)

    def frame(t):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        # бренд вверху и внизу
        text(d, (W / 2, 70), "flightcost.app", mono(34), MUTED, ramp(t, 0.1, 0.8) * (1 - ramp(t, T_SHOW1, T_SHOW1 + 0.5)), "ma")

        # заставка
        a = min(ramp(t, 0, 0.5), 1 - ramp(t, INTRO - XF, INTRO))
        if a > 0:
            dy = (1 - ramp(t, 0, 0.7)) * 40
            for i, s in enumerate(intro["title"]):
                text(d, (W / 2, 640 + i * 116 + dy), s, font("SemiBold", 96), FG, a, "ma")
            text(d, (W / 2, 640 + len(intro["title"]) * 116 + 50 + dy), intro.get("sub", ""), font("Regular", 42), MUTED,
                 a * ramp(t, 0.5, 1.1), "ma")

        # экран
        ca = min(ramp(t, T_SHOW0, T_SHOW0 + 0.7), 1 - ramp(t, T_SHOW1 - 0.1, T_SHOW1 + 0.5))
        if ca > 0:
            tv = t - T_SHOW0
            scr, v, zs, to_card = screen_at(tv)
            dy = round((1 - ramp(t, T_SHOW0, T_SHOW0 + 0.8)) * 160 + ramp(t, T_SHOW1 - 0.1, T_SHOW1 + 0.5) * -60)
            cy = CARD_Y + dy
            # подпись шага
            cap = take.caption(v)
            if cap:
                ct = take.to_video(cap["t"]) + T_SHOW0
                k = ramp(t, ct, ct + 0.45)
                ya = (1 - k) * 24
                aa = ca * k
                if cap.get("n"):
                    cxn, cyn = 104, 186 + ya
                    d.ellipse((cxn - 40, cyn - 40, cxn + 40, cyn + 40), fill=mix(SKY, aa))
                    text(d, (cxn, cyn + 2), str(cap["n"]), f_num, BG, 1, "mm") if aa > 0.5 else None
                    tx = 172
                else:
                    tx = 72
                text(d, (tx, 140 + ya), cap["text"], f_cap, FG, aa)
                text(d, (tx, 222 + ya), cap.get("sub", ""), f_sub, MUTED, aa)
            # тень и карточка
            sh_a = Image.new("RGBA", im.size, (0, 0, 0, 0))
            sh_a.paste(shadow, (CARD_X - 80, cy - 80))
            if ca < 1:
                sh_a.putalpha(sh_a.getchannel("A").point(lambda p: int(p * ca)))
            im.paste(sh_a, (0, 0), sh_a)
            if ca < 1:
                scr = Image.blend(Image.new("RGB", scr.size, BG), scr, ca)
            im.paste(scr, (CARD_X, cy), mask)
            d = ImageDraw.Draw(im)
            d.rounded_rectangle((CARD_X - 1, cy - 1, CARD_X + CARD_W, cy + card_h), RADIUS,
                                outline=mix((52, 58, 66), ca), width=2)
            # касания
            ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
            od = ImageDraw.Draw(ov)
            for e in taps:
                dt = v - e["t"]
                if -0.25 <= dt <= 0.9:
                    x, y, w, h = e["box"]
                    X, Y = to_card(x + min(w / 2, 60) if w > 160 else x + w / 2, y + h / 2)
                    X += CARD_X; Y += cy
                    if dt < 0.12:                                   # палец опускается
                        r = 26 + (1 - ramp(dt, -0.25, 0.12)) * 14
                        al = int(150 * ramp(dt, -0.25, 0.0))
                        od.ellipse((X - r, Y - r, X + r, Y + r), fill=(236, 240, 244, al))
                    if dt >= 0:                                     # волна
                        r = 26 + 70 * ease(dt / 0.8)
                        al = int(200 * (1 - ease(dt / 0.85)))
                        od.ellipse((X - r, Y - r, X + r, Y + r), outline=(0, 237, 229, al), width=5)
            for e in drags:
                t0, t1 = e["t"], e["t"] + e["ms"] / 1000
                if t0 - 0.3 <= v <= t1 + 0.4:
                    x, y, w, h = e["box"]
                    f = e["frac0"] + (e["frac1"] - e["frac0"]) * ease2((v - t0) / (t1 - t0))
                    X, Y = to_card(x + w * f, y + h / 2)
                    X += CARD_X; Y += cy
                    al = int(160 * min(ramp(v, t0 - 0.3, t0), 1 - ramp(v, t1, t1 + 0.4)))
                    od.ellipse((X - 30, Y - 30, X + 30, Y + 30), fill=(236, 240, 244, al))
            im.paste(ov, (0, 0), ov)
            d = ImageDraw.Draw(im)
            # ускорение
            x = take.fast_at(v)
            if x:
                bx, by = CARD_X + CARD_W - 150, cy + 26
                d.rounded_rectangle((bx, by, bx + 124, by + 56), 28, fill=(20, 24, 30))
                text(d, (bx + 62, by + 28), f"×{x:g}  ▸▸", font("Medium", 28), AQUA, 1, "mm")
            if take.watch:
                draw_readout(d, v, cy + card_h + 18, ca)
            else:
                text(d, (W / 2, 1840), "flightcost.app", font("Medium", 36), SKY, ca * 0.9, "ma")

        # концовка
        a = ramp(t, T_SHOW1, T_SHOW1 + 0.6)
        if a > 0:
            for i, s in enumerate(outro["title"]):
                text(d, (W / 2, 620 + i * 104), s, font("SemiBold", 84), FG, a, "ma")
            b = ramp(t, T_SHOW1 + 0.9, T_SHOW1 + 1.5)
            yu = 620 + len(outro["title"]) * 104 + 130
            text(d, (W / 2, yu), outro.get("url", ""), font("Bold", 110), SKY, b, "ma")
            text(d, (W / 2, yu + 150), outro.get("sub", ""), font("Regular", 40), MUTED, b, "ma")
            for i, c in enumerate([SKY, AQUA, BLUE, GREEN, DEEP]):
                x = W / 2 - 2.5 * 90 + i * 90
                d.rounded_rectangle((x + 8, yu + 260, x + 82, yu + 272), 6, fill=mix(c, b))
        return im

    if stills:
        for s in stills:
            frame(s).save(os.path.join(os.path.dirname(out) or ".", f"still_{s:05.1f}.png"))
        return total

    n = int(total * FPS)
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-pix_fmt", "yuv420p",
                          "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(frame(i / FPS).tobytes())
    p.stdin.close(); p.wait()
    return total


if __name__ == "__main__":
    ensure_fonts()
    take = Take(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else "promo.mp4"
    stills = [float(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else None
    total = build(take, out, stills)
    print(f"ролик {total:.1f} с → {out}")
