"""Renders video v3 frame by frame: stage.html + live app windows (demo server on :8080)."""
import sys, json, pathlib
from playwright.sync_api import sync_playwright
from timeline import *

OUT = pathlib.Path("frames"); OUT.mkdir(exist_ok=True)
STAGE = pathlib.Path("stage.html").read_text()
import os, re
LANG = os.environ.get("VIDEO_LANG", "ru")
TR = lambda s: s
if LANG == "uz":   # Uzbek video: our texts in Uzbek, the app interface stays Russian
    import texts_uz as U
    for cid, inner in U.CAPS.items():
        STAGE = re.sub(rf'(<div class="cap" id="{cid}">).*?(</div>\n)', lambda m: m.group(1) + inner + "</div>\n", STAGE, count=1)
    for a_, b_ in U.STAGE:
        assert a_ in STAGE, a_
        STAGE = STAGE.replace(a_, b_)
    PAIN = [dict(P, msgs=[(t_, U.PAIN[m_]) for t_, m_ in P["msgs"]]) for P in PAIN]
    TR = lambda s: U.CALLOUTS.get(s, s)
ASSETS = pathlib.Path("assets").resolve()
only = [float(a) for a in sys.argv[1:]]
ease = lambda x: 1 - (1 - min(1, max(0, x))) ** 3
eio = lambda x: (lambda x: 4*x**3 if x < .5 else 1-(-2*x+2)**3/2)(min(1, max(0, x)))
clamp = lambda x: min(1, max(0, x))
LABELS = {"0": ("new", "Новый"), "1": ("bought", "Выкуплен"), "2": ("warehouse", "На складе"), "3": ("cargo", "Отправлен"), "4": ("delivered", "Доставлен")}

STEP_JS = """const p=%s;
  let st=document.getElementById('vstyle');if(!st){st=document.createElement('style');st.id='vstyle';st.textContent='.step::before{background:linear-gradient(90deg,var(--accent) calc(var(--f,0)*100%%),var(--surface-3) 0)!important}.step .icon{transition:none!important}.step.current .icon{box-shadow:none!important}';document.head.appendChild(st)}
  [...document.querySelectorAll('.stepper .step')].forEach((s,i)=>{
    s.classList.remove('done','current');if(p>=i)s.classList.add('done');
    s.style.setProperty('--f',Math.min(1,Math.max(0,p-(i-1))));
    const ic=s.querySelector('.icon');const k=p>=i?Math.max(0,1-(p-i)/.4):0;
    ic.style.transform='scale('+(1+.25*Math.sin(k*Math.PI))+')';
    ic.style.boxShadow=(p>=i&&p<i+1)?'0 0 0 5px var(--accent-soft)':'none';
    const w=s.querySelector('.when');if(w)w.style.opacity=p>=i+.3?1:0;
  });
  const bd=document.querySelector('.badge');if(bd){const m=%s;const k=Math.min(4,Math.floor(p+.02));bd.className='badge s-'+m[k][0];bd.textContent=m[k][1]}"""

import time, urllib.request
_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # localhost must not go through a proxy
for _ in range(60):   # wait for the demo server, otherwise app windows load an error page
    try:
        _direct.open("http://localhost:8080/api/config", timeout=2); break
    except Exception: time.sleep(1)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args=["--no-sandbox", "--no-proxy-server"])
    ctx = b.new_context(viewport={"width": 1080, "height": 1920}, device_scale_factor=1, locale="ru-RU", timezone_id="Asia/Seoul", color_scheme="light")
    # per-window demo role: windows named fa*/fd are the admin, the rest the client (all on one origin)
    ctx.add_init_script("""(()=>{const role=(/^(fa|fd)/.test(window.name))?'admin':'client';const o=Storage.prototype.getItem;Storage.prototype.getItem=function(k){return k==='crm-demo-role'?role:o.call(this,k)}})()""")
    # no internet here: block external fonts/scripts so nothing hangs
    ctx.route(lambda u: not (u.startswith("http://localhost:8080") or u.startswith("data:") or u.startswith("blob:")), lambda r: r.abort())
    page = ctx.new_page()
    page.route("http://localhost:8080/__stage.html", lambda r: r.fulfill(body=STAGE, content_type="text/html; charset=utf-8"))
    page.goto("http://localhost:8080/__stage.html", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    page.evaluate(f"initChaos({json.dumps(chaos_times())});window.PAIN={json.dumps(PAIN)}")
    F = {n: page.frame(name=n) for n in ("fc", "fa2", "fd")}
    ev = lambda n, js: F[n].evaluate(f"(()=>{{{js}}})()")
    def nav(n, h, wait=900):
        ev(n, f"location.hash={json.dumps(h)}"); page.wait_for_timeout(wait)
    def frect(n):
        return page.evaluate(f"(()=>{{const e=document.getElementById('{n}');const r=e.getBoundingClientRect();return [r.left,r.top,r.width/e.offsetWidth]}})()")
    def box(n, js):
        r = ev(n, js)
        if not r: return None
        L, T, s = frect(n); return (L + r[0]*s, T + r[1]*s, r[2]*s, r[3]*s)
    def rect_of(sel): return f"const e=document.querySelector({json.dumps(sel)});if(!e)return null;const r=e.getBoundingClientRect();return [r.left,r.top,r.width,r.height]"
    def el_rect(js_el): return f"const e={js_el};if(!e)return null;const r=e.getBoundingClientRect();return [r.left,r.top,r.width,r.height]"
    def btn_js(text, exact=False, tags="button,a,label"):
        cond = f"x.textContent.trim()==={json.dumps(text)}" if exact else f"x.textContent.includes({json.dumps(text)})"
        return f"[...document.querySelectorAll('{tags}')].find(x=>{cond})"
    def click_js(n, js_el): ev(n, f"const e={js_el};if(e)e.click()")
    def top_of(n, js_el): return ev(n, f"const e={js_el};return e?e.getBoundingClientRect().top+scrollY:0") or 0
    scroll = lambda n, y: ev(n, f"scrollTo(0,{y})")
    def union(n, js_list):
        return box(n, f"const es=[{js_list}].filter(Boolean);if(!es.length)return null;const rs=es.map(e=>e.getBoundingClientRect());const l=Math.min(...rs.map(r=>r.left)),t=Math.min(...rs.map(r=>r.top)),r=Math.max(...rs.map(r=>r.right)),b=Math.max(...rs.map(r=>r.bottom));return [l,t,r-l,b-t]")
    DT = lambda txt: f"[...document.querySelectorAll('dt')].find(x=>x.textContent.trim()==={json.dumps(txt)})"
    CARD = lambda oid: "[...document.querySelectorAll('article.order-card')].find(x=>x.textContent.includes('Tech Fleece'))"   # N51
    # smallest element inside the N6 card whose text matches
    def in_card(oid, cond): return f"(()=>{{const c={CARD(oid)};if(!c)return null;return [...c.querySelectorAll('*')].filter(x=>{cond}).sort((a,b)=>a.textContent.length-b.textContent.length)[0]||null}})()"

    st = {"done": set(), "tap": None, "y": {}, "hl": {}, "zoom": None}
    def once(key):
        if key in st["done"]: return False
        st["done"].add(key); return True
    def tap_box(t0, bx):
        if bx: st["tap"] = (t0, bx[0] + bx[2]/2, bx[1] + bx[3]/2)
    def ring(bx, o, g=False, pad=8):
        return {"x": bx[0] - pad, "y": bx[1] - pad, "w": bx[2] + 2*pad, "h": bx[3] + 2*pad, "o": o, "g": g}
    fade = lambda t, a, z, fi=.25, fo=.3: clamp((t - a) / fi) * clamp((z - t) / fo)

    times = only or [i / FPS for i in range(int(DURATION * FPS))]
    for i, t in enumerate(times):
        # ---------- one-shot events (in time order) ----------
        if t >= TAP_OPEN and once("open"):
            tap_box(TAP_OPEN, page.evaluate("(()=>{const r=document.getElementById('inbtn').getBoundingClientRect();return [r.left,r.top,r.width,r.height]})()"))
        if t >= 12.3 and once("bal"): nav("fc", "#/balance")
        if t >= 20.3 and once("ships"): nav("fc", "#/shipments")
        if t >= SHIP_TAP and once("shiptap"): tap_box(SHIP_TAP, box("fc", rect_of('a[href^="#/shipments/"]')))
        if t >= SHIP_TAP + .1 and once("shipnav"):
            h = ev("fc", "const e=document.querySelector('a[href^=\"#/shipments/\"]');return e?e.getAttribute('href'):null")
            if h: nav("fc", h, 1500)
        if t >= 28.3 and once("orders"): nav("fc", "#/orders")
        for pt, name in PILLS:
            if t >= pt and once("pill" + name): tap_box(pt, box("fc", el_rect(btn_js(name, True, "button"))))
            if t >= pt + .08 and once("pillc" + name): click_js("fc", btn_js(name, True, "button")); page.wait_for_timeout(500)
        if t >= 35.95 and once("n6"):
            nav("fc", "#/orders/N51", 1000)
            st["y"]["c"] = max(0, top_of("fc", "[...document.querySelectorAll('.card')].find(x=>x.textContent.includes('Цена'))") - 12)
            st["y"]["a"] = max(0, top_of("fa2", "[...document.querySelectorAll('h3')].find(x=>x.textContent.includes('Для администратора'))") - 70)
        if t >= 38.6 and once("green"):
            ev("fa2", f"const d={DT('Прибыль')};if(d&&d.nextElementSibling){{d.nextElementSibling.style.color='#16a34a';d.nextElementSibling.style.fontWeight='800'}}")
        if t >= TAP_WAREHOUSE and once("tapwh"): tap_box(TAP_WAREHOUSE, box("fa2", el_rect(btn_js("На склад", False, "button"))))
        if t >= TAP_WAREHOUSE + .1 and once("clickwh"): click_js("fa2", btn_js("На склад", False, "button")); page.wait_for_timeout(900)
        if t >= TAP_TABS and once("taptabs"): tap_box(TAP_TABS, box("fa2", rect_of('.tabbar a[href="#/orders"]')))
        if t >= TAP_TABS + .1 and once("navtabs"):
            ev("fa2", "if(!document.getElementById('notoast')){const s=document.createElement('style');s.id='notoast';s.textContent='.toast-stack{display:none!important}';document.head.appendChild(s)}")
            ev("fc", "location.hash='#/orders';location.reload()"); page.wait_for_timeout(1800); F["fc"] = page.frame(name="fc")
            nav("fa2", "#/orders", 900)

        if t >= 47.95 and once("new"):
            ev("fa2", "const s=document.createElement('style');s.id='notoast';s.textContent='.toast-stack{display:none!important}';document.head.appendChild(s)")
            nav("fa2", "#/orders/new", 1300)
        if t >= TAP_ADD_PHOTO and once("tapphoto"): tap_box(TAP_ADD_PHOTO, box("fa2", rect_of("label.btn")))
        if t >= UPLOAD and once("upload"):
            page.frame_locator("#fa2").locator("input[type=file]").first.set_input_files(str(ASSETS / "1.jpg")); page.wait_for_timeout(2000)
        if t >= TAP_AI and once("tapai"): tap_box(TAP_AI, box("fa2", rect_of(".btn.ai-fill")))
        if t >= SCAN_TO and once("ai"):
            ev("fa2", "const s=document.getElementById('notoast');if(s)s.remove();const b=document.querySelector('.btn.ai-fill');if(b)b.click()"); page.wait_for_timeout(900)
        if t >= TAP_CREATE and once("tapcreate"): tap_box(TAP_CREATE, box("fa2", el_rect(btn_js("Создать заказ", False, "button"))))
        if t >= DESK_SHIPMENTS and once("dship"): tap_box(DESK_SHIPMENTS, box("fd", rect_of('aside a[href="#/shipments"]')))
        if t >= DESK_SHIPMENTS + .1 and once("dshipn"): nav("fd", "#/shipments", 900)
        if t >= DESK_DASH and once("ddash"): tap_box(DESK_DASH, box("fd", rect_of('aside a[href="#/"]')))
        if t >= DESK_DASH + .1 and once("ddashn"):
            nav("fd", "#/", 1000)
            ev("fd", "document.querySelectorAll('.kpi .value').forEach((v,i)=>{if(i<2)v.dataset.final=v.textContent})")
        if t >= ZOOM_FROM - .05 and once("zoomcalc"):
            page.evaluate(f"setT({t},{{}})")
            kb = union("fd", "...[...document.querySelectorAll('.kpi')].slice(0,2)")
            lp = page.evaluate("(()=>{const r=document.getElementById('laptop').getBoundingClientRect();return [r.left,r.top]})()")
            if kb:
                cx, cy = kb[0] + kb[2]/2, kb[1] + kb[3]/2
                st["zoom"] = {"ox": cx - lp[0], "oy": cy - lp[1], "s": 1.9, "dy": 1000 - cy}

        # ---------- per-frame app state ----------
        if S3 <= t < S4: scroll("fc", eio((t - 16.2) / 3.2) * 560)
        if S4 <= t < S5:
            scroll("fc", eio((t - 25.9) / 1.7) * 560 if t >= SHIP_TAP + .1 else 0)
            if t >= SHIP_TAP + .1: ev("fc", f"const c=document.querySelector('.carousel');if(c)c.scrollLeft={eio((t - SWIPE) / .4)}*(c.scrollWidth-c.clientWidth)")
        if S5 <= t < 35.95: scroll("fc", 0)
        if 35.95 <= t < TAP_TABS + .1:
            scroll("fc", eio((t - 36.2) / .9) * st["y"].get("c", 0)); scroll("fa2", eio((t - 36.4) / .9) * st["y"].get("a", 0))
            if t >= SYNC - .05: ev("fc", STEP_JS % (1 + min(1, max(0, (t - SYNC) / 1.4)), json.dumps(LABELS)))
        if TAP_TABS + .1 <= t < 47.95:
            for n_, key in (("fc", "lc"), ("fa2", "la")):   # measure once the list has rendered
                if not st["y"].get(key):
                    y_ = top_of(n_, CARD("N6")) or 0
                    if y_ <= 0: page.wait_for_timeout(400); y_ = top_of(n_, CARD("N6")) or 0
                    if y_ > 0: st["y"][key] = max(1, y_ - 150)
            k = eio((t - TAP_TABS - .2) / .45); scroll("fc", k * st["y"].get("lc", 0)); scroll("fa2", k * st["y"].get("la", 0))
        if 47.95 <= t < S8 + .3: scroll("fa2", eio((t - 53.6) / 1.2) * 1200 if t >= 53.6 else 0)
        if DESK_DASH + .1 <= t < S9:
            k = eio((t - COUNT_FROM) / (COUNT_TO - COUNT_FROM))
            ev("fd", f"document.querySelectorAll('.kpi .value').forEach((v,i)=>{{if(i>1||!v.dataset.final)return;const f=+v.dataset.final.replace(/[^0-9]/g,'');v.textContent={json.dumps(t >= COUNT_TO)}?v.dataset.final:'₩'+Math.round(f*{k}).toLocaleString('en-US')}})")

        zoom = None
        if st["zoom"] and ZOOM_FROM <= t < ZOOM_TO + .1:
            zoom = dict(st["zoom"], k=eio((t - ZOOM_FROM) / .5) * (1 - eio((t - (ZOOM_TO - .5)) / .5)))
        page.evaluate(f"setT({t},{json.dumps({'zoom': zoom} if zoom else {})})")   # place everything first, then measure overlays
        extra = {"rings": [], "callouts": []}
        if zoom: extra["zoom"] = zoom
        # scene 4: shipment photos and track number
        if SHUTTER1 <= t < SHUTTER2 + .6:
            bx = box("fc", rect_of(".carousel"))
            if bx: extra["rings"].append(ring(bx, fade(t, SHUTTER1, SHUTTER2 + .6, .12), True))
        if STAMP <= t < STAMP + 1.2:
            bx = union("fc", f"{DT('Трек-номер')},{DT('Трек-номер')}&&{DT('Трек-номер')}.nextElementSibling")
            if bx: extra["rings"].append(ring(bx, fade(t, STAMP, STAMP + 1.2, .12), pad=10))
        # scene 6: comparison rings (rings stay until the tap, only the latest callout shows)
        if HL[0][0] - .05 <= t < 41.1:
            if not st["hl"] and t >= 37.2:
                st["hl"] = {
                    "client-price": box("fc", "const e=[...document.querySelectorAll('.card')].find(x=>x.textContent.includes('Цена'));if(!e)return null;const r=e.getBoundingClientRect();return [r.left,r.top,r.width,Math.min(r.height,96)]"),
                    "admin-profit": union("fa2", f"{DT('Закупка')},{DT('Прибыль')}&&{DT('Прибыль')}.nextElementSibling"),
                    "admin-buttons": union("fa2", "...[...document.querySelectorAll('button')].filter(x=>['На склад','В отправку','Перезаказ','Отменить','Копия','Удалить'].some(s=>x.textContent.includes(s)))"),
                }
            texts = {"client-price": "Клиент видит только цену", "admin-profit": "Ваша маржа на каждом заказе", "admin-buttons": "Управление заказом"}
            for k_, (ht, name) in enumerate(HL):
                bx = st["hl"].get(name) if st["hl"] else None
                if not bx or t < ht: continue
                o = fade(t, ht, 41.1); g = name == "admin-profit"
                extra["rings"].append(ring(bx, o, g))
                until = 40.0 if name == "client-price" else (HL[k_ + 1][0] if k_ + 1 < len(HL) else 41.1)
                extra["callouts"].append({"x": 273 if name == "client-price" else 807, "y": 1668, "text": TR(texts[name]), "o": fade(t, ht, until), "g": g, "ax": -50})
        if SYNC - .2 <= t < TAP_TABS:
            bx = box("fc", rect_of(".stepper"))
            if bx:
                o = fade(t, SYNC - .2, TAP_TABS)
                extra["rings"].append(ring(bx, o, True)); extra["callouts"].append({"x": 273, "y": 1668, "text": TR("Клиент видит сразу"), "o": o, "g": True, "ax": -50})
        if HL_LIST <= t < 47.7:
            o = fade(t, HL_LIST, 47.7)
            bc = box("fc", el_rect(in_card("N6", "/^₩/.test(x.textContent.trim())")))
            ba = box("fa2", el_rect(in_card("N6", "x.textContent.toLowerCase().includes('закупка')")))
            if bc: extra["rings"].append(ring(bc, o, pad=6)); extra["callouts"].append({"x": 273, "y": 1668, "text": TR("Клиент видит цену"), "o": o, "ax": -50})
            if ba: extra["rings"].append(ring(ba, clamp((t - HL_LIST - .3) / .25) * clamp((47.7 - t) / .3), True, 6)); extra["callouts"].append({"x": 807, "y": 1668, "text": TR("Закупка видна только вам"), "o": clamp((t - HL_LIST - .3) / .25) * clamp((47.7 - t) / .3), "g": True, "ax": -50})
        # scene 7: scan over the uploaded photo
        if SCAN_FROM <= t < SCAN_TO + .3:
            bx = box("fa2", rect_of("img[alt='Фото']"))
            if bx: extra["scan"] = {"x": bx[0] - 6, "y": bx[1] - 6, "w": bx[2] + 12, "h": bx[3] + 12, "o": fade(t, SCAN_FROM, SCAN_TO + .3, .2), "k": ((t - SCAN_FROM) / .7) % 1}
        # scene 8: profit column, dashboard cards, «Моя прибыль»
        if DESK_PROFIT_HL <= t < DESK_SHIPMENTS:
            bx = union("fd", "...(()=>{const ths=[...document.querySelectorAll('th')];const i=ths.findIndex(x=>x.textContent.trim()==='Прибыль');if(i<0)return [];return [ths[i],...document.querySelectorAll('tbody tr td:nth-child('+(i+1)+')')]})()")
            if bx:   # clip to the visible part of the laptop screen
                L_, T_, s_ = frect("fd"); bottom = T_ + 751 * s_ - 6
                bx = (bx[0], bx[1], bx[2], min(bx[3], bottom - bx[1]))
                o = fade(t, DESK_PROFIT_HL, DESK_SHIPMENTS)
                extra["rings"].append(ring(bx, o, True, 4)); extra["callouts"].append({"x": 540, "y": 560, "text": TR("Прибыль по каждому заказу"), "o": o, "g": True, "ax": -50})
        if 62.0 <= t < ZOOM_TO - .5:
            bx = union("fd", "...[...document.querySelectorAll('.kpi')].slice(0,2)")
            if bx:
                o = fade(t, 62.0, ZOOM_TO - .5)
                extra["rings"].append(ring(bx, o, True, 6)); extra["callouts"].append({"x": 540, "y": 1560, "text": TR("Без Excel и калькулятора"), "o": o, "g": True, "ax": -50})
        if st["tap"] and 0 <= t - st["tap"][0] <= .5:
            extra["tap"] = {"k": (t - st["tap"][0]) / .5, "x": st["tap"][1], "y": st["tap"][2]}
        page.evaluate(f"setT({t},{json.dumps(extra)})")
        name = f"still-{t:05.2f}.jpg" if only else f"f{i:04d}.jpg"
        page.screenshot(path=str(OUT / name), type="jpeg", quality=93)
        if i % 60 == 0: print("frame", i, f"t={t:.1f}", flush=True)
    b.close()
