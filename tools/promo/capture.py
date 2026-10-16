"""Съёмка видеоинструкции с живой витрины.

    python3 capture.py scenario.json [--base https://flightcost.app] [--out take]

Прогоняет сценарий в эмуляции телефона (390×693 css, плотность 3 → кадр
1170×2079, ровно 9:16) и пишет в папку --out:
  frames/NNNNN.jpg  кадры
  log.json          время каждого кадра, подписи шагов, касания и приближения
                    с рамками элементов — по нему монтирует montage.py

Часы виртуальные. Прокрутку, ползунок и набор текста скрипт двигает сам и
снимает кадр после каждого шага, назначая ему время по сценарию, — так
движение плавное, сколько бы ни длился снимок (полное разрешение ≈14 кадров/с).
Ожидания (расчёт, отклик) снимаются в реальном времени.
"""
import argparse, asyncio, base64, json, os, time
from playwright.async_api import async_playwright

VW, VH, DPR = 390, 693, 3
FPS = 30


def ease(x):
    return 3 * x * x - 2 * x * x * x          # мягкие разгон и торможение


async def run(a):
    sc = json.load(open(a.scenario, encoding="utf-8"))
    # высота кадра — под безопасную зону Shorts: чем ниже кадр, тем крупнее
    # экран в ролике (montage.layout), ширина остаётся телефонной
    VW, VH = sc.get("viewport", [390, 693])
    # десктоп: мышь вместо пальца, кадр 16:9, прокрутка внутри панелей
    desktop = sc.get("device") == "desktop"
    DPR = sc.get("dpr", 1.5 if desktop else 3)
    fdir = os.path.join(a.out, "frames")
    os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(fdir):
        os.remove(os.path.join(fdir, f))
    times, events, reads = [], [], []
    watch = sc.get("watch", [])
    watch_js = "()=>[" + ",".join(f"(()=>{{try{{return String({w['js']})}}catch(e){{return ''}}}})()"
                                   for w in watch) + "]"
    vt = 0.0                                    # виртуальное время ролика, с

    def log(kind, **kw):
        events.append({"t": round(vt, 3), "kind": kind, **kw})

    async with async_playwright() as p:
        # свой Chromium Playwright, а если он не скачан — установленный Google Chrome
        b, last = None, None
        for ch in ([a.channel] if a.channel else [None, "chrome", "msedge"]):
            try:
                b = await p.chromium.launch(headless=not a.headed, channel=ch)
                print("браузер:", ch or "chromium из playwright")
                break
            except Exception as e:
                last = e
        if b is None:
            raise SystemExit(f"браузер не запустился: {str(last)[:300]}\n"
                             "поставьте Google Chrome или выполните `playwright install chromium`")
        dev = {} if desktop else dict(
            is_mobile=True, has_touch=True,
            user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
                        "Mobile/15E148 Safari/604.1"))
        ctx = await b.new_context(
            viewport={"width": VW, "height": VH}, device_scale_factor=DPR,
            locale=sc.get("locale", "en-US"), **dev)
        pg = await ctx.new_page()
        cdp = await ctx.new_cdp_session(pg)
        await cdp.send("Emulation.setDeviceMetricsOverride",
                       {"width": VW, "height": VH, "deviceScaleFactor": DPR, "mobile": not desktop})

        async def press(el):
            """касание на телефоне, щелчок мышью на десктопе"""
            await (el.click() if desktop else el.tap())

        async def shot(dt):
            """снять кадр, поставить его на текущее время, сдвинуть часы на dt"""
            nonlocal vt
            r = await cdp.send("Page.captureScreenshot",
                               {"format": "jpeg", "quality": 88, "optimizeForSpeed": True})
            open(os.path.join(fdir, f"{len(times):05d}.jpg"), "wb").write(base64.b64decode(r["data"]))
            times.append(round(vt, 3))
            if watch:
                reads.append(await pg.evaluate(watch_js))
            vt += dt

        async def realtime(ms):
            """снимать подряд ms миллисекунд реального времени"""
            nonlocal vt
            end = time.time() + ms / 1000
            while True:
                t = time.time()
                await shot(0)
                vt += time.time() - t
                if time.time() >= end:
                    break

        async def box(sel, nth=0, scroll=True):
            el = pg.locator(sel).nth(nth)
            if scroll:
                await el.scroll_into_view_if_needed(timeout=10000)
            bb = await el.bounding_box()
            return el, [round(bb["x"], 1), round(bb["y"], 1), round(bb["width"], 1), round(bb["height"], 1)]

        # Прокручивается не всегда окно: на десктопе у витрины свои панели
        # (#left, #main). Контейнер — ближайший прокручиваемый предок
        # элемента; для scrollby — элемент `in` или окно.
        PICK = """(a)=>{
          const S=e=>{const s=getComputedStyle(e);return /(auto|scroll)/.test(s.overflowY)&&e.scrollHeight>e.clientHeight+2};
          let e=a.sel?document.querySelectorAll(a.sel)[a.nth||0]:null, c=null;
          if(e&&a.self&&S(e)) c=e;
          for(let p=e&&!c?e.parentElement:null;p&&p!==document.body&&p!==document.documentElement;p=p.parentElement) if(S(p)){c=p;break}
          c=c||document.scrollingElement; window.__fcaC=c;
          const top=c===document.scrollingElement?0:c.getBoundingClientRect().top;
          const y=a.to==='el'?e.getBoundingClientRect().top-top+c.scrollTop-a.off:c.scrollTop+a.dy;
          return [c.scrollTop, Math.max(0,Math.min(y,c.scrollHeight-c.clientHeight))]}"""

        async def scroll_to(arg, ms):
            y0, y1 = await pg.evaluate(PICK, arg)
            n = max(2, round(ms / 1000 * FPS))
            for k in range(1, n + 1):
                await pg.evaluate("y=>{window.__fcaC.scrollTop=y}", y0 + (y1 - y0) * ease(k / n))
                await shot(1 / FPS)

        url = a.base.rstrip("/") + sc.get("path", "/")
        await pg.goto(url, wait_until="networkidle", timeout=90000)
        await pg.wait_for_timeout(sc.get("settle_ms", 2500))
        log("start", url=url)

        for i, s in enumerate(sc["steps"]):
            do = s["do"]
            try:
                if do == "caption":
                    log("caption", n=s.get("n"), text=s["text"], sub=s.get("sub", ""))
                elif do == "wait":
                    await realtime(s.get("ms", 1000))
                elif do in ("tap", "fill"):
                    el, bb = await box(s["sel"], s.get("nth", 0))
                    await realtime(120)
                    log("tap", box=bb, sel=s["sel"])
                    await realtime(s.get("before", 300))
                    if s.get("nav"):                      # касание уводит на другую страницу
                        async with pg.expect_navigation(wait_until="domcontentloaded",
                                                        timeout=s.get("timeout", 120000)):
                            await el.evaluate("e=>e.removeAttribute('target')")
                            await press(el)
                    else:
                        await press(el)
                    if do == "fill":
                        await el.fill("")
                        for ch in str(s["text"]):
                            await el.press(ch)
                            await shot(s.get("delay", 140) / 1000)
                        await el.dispatch_event("change")
                    await realtime(s.get("after", 500))
                elif do == "select":
                    el, bb = await box(s["sel"], s.get("nth", 0))
                    await realtime(120)
                    log("tap", box=bb, sel=s["sel"])
                    await realtime(s.get("before", 300))
                    await el.select_option(str(s["value"]))
                    await realtime(s.get("after", 900))
                elif do == "clear":
                    await pg.locator(s["sel"]).fill("")
                elif do == "type":
                    el = pg.locator(s["sel"])
                    for ch in s["text"]:
                        await el.press(ch)
                        await pg.wait_for_timeout(25)
                        await shot(s.get("delay", 120) / 1000)
                    await realtime(s.get("after", 600))
                elif do == "slide":
                    el, bb = await box(s["sel"])
                    lo = float(await el.get_attribute("min") or 0)
                    hi = float(await el.get_attribute("max") or 100)
                    v0, v1 = float(await el.input_value()), float(s["to"])
                    ms = s.get("ms", 1400)
                    log("drag", box=bb, sel=s["sel"], ms=ms,
                        frac0=(v0 - lo) / (hi - lo), frac1=(v1 - lo) / (hi - lo))
                    n = max(2, round(ms / 1000 * FPS))
                    for k in range(1, n + 1):
                        v = round(v0 + (v1 - v0) * ease(k / n))
                        await el.evaluate("(e,v)=>{if(e.value!=v){e.value=v;"
                                          "e.dispatchEvent(new Event('input',{bubbles:true}))}}", v)
                        await shot(1 / FPS)
                    await el.evaluate("e=>e.dispatchEvent(new Event('change',{bubbles:true}))")
                    await realtime(s.get("after", 800))
                elif do == "scroll":                  # элемент к верху своей панели
                    await scroll_to({"sel": s["sel"], "nth": s.get("nth", 0), "to": "el",
                                     "off": s.get("offset", 60)}, s.get("ms", 1200))
                elif do == "scrollby":
                    await scroll_to({"sel": s.get("in"), "self": True, "to": "by", "dy": s["dy"]},
                                    s.get("ms", 1200))
                elif do == "zoom":                    # приближение делает монтаж
                    # `box` — область кадра в css-пикселях вместо элемента;
                    # `wait: false` — приближение идёт поверх следующих шагов
                    if "box" in s:
                        bb, sel = s["box"], ""
                    else:
                        _, bb = await box(s["sel"], s.get("nth", 0))
                        sel = s["sel"]
                    log("zoom", box=bb, sel=sel, ms=s.get("ms", 2500), scale=s.get("scale", 1.7))
                    if s.get("wait", True):
                        await realtime(s.get("ms", 2500))
                elif do == "waitfor":                 # долгий расчёт: монтаж ускорит
                    log("fast_on", x=s.get("speed", 6), label=s.get("label", ""))
                    task = asyncio.ensure_future(
                        pg.wait_for_function(s["js"], timeout=s.get("timeout", 120000), polling=250)
                        if "js" in s else
                        pg.locator(s["sel"]).first.wait_for(state=s.get("state", "visible"),
                                                            timeout=s.get("timeout", 120000)))
                    while not task.done():
                        await realtime(250)
                    task.result()
                    log("fast_off")
                    await realtime(s.get("after", 600))
                elif do == "js":
                    await pg.evaluate(s["js"])
                    await realtime(s.get("after", 300))
                else:
                    raise ValueError(f"неизвестное действие {do}")
            except Exception as e:
                log("error", step=i, do=do, msg=str(e)[:300])
                if not s.get("optional"):
                    print(f"шаг {i} ({do}) упал: {e}")
                    break
                print(f"шаг {i} ({do}) необязательный, пропущен: {str(e)[:120]}")

        await realtime(sc.get("tail_ms", 800))
        log("end")
        await b.close()

    json.dump({"viewport": [VW, VH, DPR], "device": "desktop" if desktop else "phone", "frames": times, "events": events,
               "watch": [{"label": w["label"], **({"kind": w["kind"]} if "kind" in w else {})} for w in watch],
               "reads": reads, "scenario": a.scenario},
              open(os.path.join(a.out, "log.json"), "w"), ensure_ascii=False, indent=1)
    errs = [e for e in events if e["kind"] == "error"]
    print(f"кадров {len(times)}, длительность {vt:.1f} с, ошибок {len(errs)} → {a.out}/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--base", default="https://flightcost.app")
    ap.add_argument("--out", default="take")
    ap.add_argument("--headed", action="store_true", help="показывать окно браузера")
    ap.add_argument("--channel", help="chrome, msedge…; по умолчанию свой Chromium, иначе установленный Chrome")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
