"""Renders video v3 frame by frame: stage.html + live app windows (demo server on :8080)."""
import sys, json, pathlib
from playwright.sync_api import sync_playwright
from timeline import *

OUT = pathlib.Path("frames"); OUT.mkdir(exist_ok=True)
STAGE = pathlib.Path("stage.html").read_text()
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

AIBTN = """let b=document.getElementById('aibtn');
  if(!b){const f=[...document.querySelectorAll('.field')].find(x=>x.textContent.trim().startsWith('Бренд'));if(!f)return;
    b=document.createElement('button');b.id='aibtn';b.className='btn';b.type='button';
    b.style.cssText='width:100%%;justify-content:center;margin:2px 0 10px;gap:8px;position:relative;overflow:hidden;height:48px;font-weight:700';f.parentNode.insertBefore(b,f)}
  const s=%s;
  const spark='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 16l.7 1.8L21.5 18.5l-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z"/></svg>';
  const ok='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg>';
  b.style.display=s.o>0?'inline-flex':'none';b.style.opacity=s.o;
  b.style.background=s.mode==='done'?'#dcfce7':'';b.style.color=s.mode==='done'?'#166534':'';
  b.innerHTML=(s.mode==='go'?'<span style="position:absolute;inset:0;background:linear-gradient(100deg,transparent '+(s.x-30)+'%%,rgba(120,150,220,.4) '+s.x+'%%,transparent '+(s.x+30)+'%%)"></span>':'')+(s.mode==='done'?ok:spark)+'<span style="position:relative">'+s.text+'</span>';"""

TYPE = [("Nike", "On"), ("Air Max 95", "Cloud 5 Waterproof"), ("270", "270")]

import time, urllib.request
for _ in range(60):   # wait for the demo server, otherwise app windows load an error page
    try:
        urllib.request.urlopen("http://localhost:8080/api/config", timeout=2); break
    except Exception: time.sleep(1)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1080, "height": 1920}, device_scale_factor=1, locale="ru-RU", timezone_id="Asia/Seoul", color_scheme="light")
    # per-window demo role: windows named fa*/fd are the admin, the rest the client (all on one origin)
    ctx.add_init_script("""(()=>{const role=(/^(fa|fd)/.test(window.name))?'admin':'client';const o=Storage.prototype.getItem;Storage.prototype.getItem=function(k){return k==='crm-demo-role'?role:o.call(this,k)}})()""")
    # no internet here: block external fonts/scripts so nothing hangs
    ctx.route(lambda u: not (u.startswith("http://localhost:8080") or u.startswith("data:") or u.startswith("blob:")), lambda r: r.abort())
    page = ctx.new_page()
    page.route("http://localhost:8080/__stage.html", lambda r: r.fulfill(body=STAGE, content_type="text/html; charset=utf-8"))
    page.goto("http://localhost:8080/__stage.html", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    page.evaluate(f"initChaos({json.dumps(chaos_times())})")
    F = {n: page.frame(name=n) for n in ("fc", "fa2", "fd")}
    if __import__("os").environ.get("DBG"):
        for f in page.frames: print("FRAME", repr(f.name), f.url[:50], f.is_detached(), len(f.content()))
    ev = lambda n, js: F[n].evaluate(f"(()=>{{{js}}})()")
    def nav(n, h, wait=900):
        ev(n, f"location.hash={json.dumps(h)}"); page.wait_for_timeout(wait)
    def frect(n):   # iframe box on the stage → (left, top, scale)
        r = page.evaluate(f"(()=>{{const e=document.getElementById('{n}');const r=e.getBoundingClientRect();return [r.left,r.top,r.width/e.offsetWidth]}})()")
        return r
    def box(n, js):  # js returns [l,t,w,h] in the window → stage box
        r = ev(n, js)
        if not r: return None
        L, T, s = frect(n); return (L + r[0]*s, T + r[1]*s, r[2]*s, r[3]*s)
    def rect_of(sel): return f"const e=document.querySelector({json.dumps(sel)});if(!e)return null;const r=e.getBoundingClientRect();return [r.left,r.top,r.width,r.height]"
    def btn_rect(text, exact=False):
        cond = f"x.textContent.trim()==={json.dumps(text)}" if exact else f"x.textContent.includes({json.dumps(text)})"
        return f"const e=[...document.querySelectorAll('button,a,label')].find(x=>{cond});if(!e)return null;const r=e.getBoundingClientRect();return [r.left,r.top,r.width,r.height]"
    def click_text(n, text, exact=True):
        cond = f"x.textContent.trim()==={json.dumps(text)}" if exact else f"x.textContent.includes({json.dumps(text)})"
        ev(n, f"const e=[...document.querySelectorAll('button')].find(x=>{cond});if(e)e.click()")
    def top_of(n, js_el):
        return ev(n, f"const e={js_el};return e?e.getBoundingClientRect().top+scrollY:0") or 0
    scroll = lambda n, y: ev(n, f"scrollTo(0,{y})")
    def union(n, js_list):  # union box of several elements
        return box(n, f"const es=[{js_list}].filter(Boolean);if(!es.length)return null;const rs=es.map(e=>e.getBoundingClientRect());const l=Math.min(...rs.map(r=>r.left)),t=Math.min(...rs.map(r=>r.top)),r=Math.max(...rs.map(r=>r.right)),b=Math.max(...rs.map(r=>r.bottom));return [l,t,r-l,b-t]")
    DT = lambda txt: f"[...document.querySelectorAll('dt')].find(x=>x.textContent.trim()==={json.dumps(txt)})"

    st = {"done": set(), "tap": None, "y": {}, "hl": {}}
    def once(key):
        if key in st["done"]: return False
        st["done"].add(key); return True
    def tap_box(t0, bx):
        if bx: st["tap"] = (t0, bx[0] + bx[2]/2, bx[1] + bx[3]/2)

    times = only or [i / FPS for i in range(int(DURATION * FPS))]
    for i, t in enumerate(times):
        # ---------- one-shot events (in time order) ----------
        if t >= TAP_OPEN and once("open"):
            r = page.evaluate("(()=>{const r=document.getElementById('inbtn').getBoundingClientRect();return [r.left,r.top,r.width,r.height]})()"); tap_box(TAP_OPEN, r)
        if t >= 12.3 and once("bal"): nav("fc", "#/balance")
        if t >= 19.35 and once("ships"): nav("fc", "#/shipments")
        if t >= SHIP_TAP and once("shiptap"): tap_box(SHIP_TAP, box("fc", rect_of('a[href^="#/shipments/"]')))
        if t >= SHIP_TAP + .1 and once("shipnav"):
            h = ev("fc", "const e=document.querySelector('a[href^=\"#/shipments/\"]');return e?e.getAttribute('href'):null")
            if h: nav("fc", h, 1400)
        if t >= 26.35 and once("orders"): nav("fc", "#/orders")
        for pt, name in PILLS:
            if t >= pt and once("pill" + name): tap_box(pt, box("fc", btn_rect(name, True)))
            if t >= pt + .08 and once("pillc" + name): click_text("fc", name); page.wait_for_timeout(500)
        if t >= 33.95 and once("n6"):
            nav("fc", "#/orders/N6", 1000)
            st["y"]["c"] = max(0, top_of("fc", "[...document.querySelectorAll('.card')].find(x=>x.textContent.includes('Цена'))") - 12)
            st["y"]["a"] = max(0, top_of("fa2", "[...document.querySelectorAll('h3')].find(x=>x.textContent.includes('Для администратора'))") - 70)
        if t >= 38.3 and once("green"):
            ev("fa2", f"const d={DT('Прибыль')};if(d&&d.nextElementSibling){{d.nextElementSibling.style.color='#16a34a';d.nextElementSibling.style.fontWeight='800'}}")
        if t >= TAP_WAREHOUSE and once("tapwh"): tap_box(TAP_WAREHOUSE, box("fa2", btn_rect("На склад")))
        if t >= TAP_WAREHOUSE + .1 and once("clickwh"): click_text("fa2", "На склад", False); page.wait_for_timeout(900)
        if t >= 47.95 and once("new"):
            ev("fa2", "const s=document.createElement('style');s.textContent='.toast-stack{display:none!important}';document.head.appendChild(s)")
            nav("fa2", "#/orders/new", 1300)
        if t >= TAP_ADD_PHOTO and once("tapphoto"): tap_box(TAP_ADD_PHOTO, box("fa2", rect_of("label.btn")))
        if t >= UPLOAD and once("upload"):
            page.frame_locator("#fa2").locator("input[type=file]").first.set_input_files(str(ASSETS / "1.jpg")); page.wait_for_timeout(2000)
        if t >= TAP_RECOGNIZE and once("tapai"): tap_box(TAP_RECOGNIZE, box("fa2", rect_of("#aibtn")))
        if t >= TAP_CREATE and once("tapcreate"): tap_box(TAP_CREATE, box("fa2", rect_of(".actions .btn.primary")))
        for dt, name in DESK_TAPS:
            if t >= dt and once("d" + name): tap_box(dt, box("fd", btn_rect(name, True)))
            if t >= dt + .08 and once("dc" + name): click_text("fd", name); page.wait_for_timeout(500)

        # ---------- per-frame state ----------
        if S3 <= t < S4: scroll("fc", eio((t - 14.6) / 3.2) * 560)
        if S4 <= t < S5: scroll("fc", eio((t - 23.2) / 2.2) * 560 if t >= 21.4 else 0)
        if S5 <= t < S6: scroll("fc", 0)
        if 33.95 <= t < 48:
            scroll("fc", eio((t - 34.2) / .9) * st["y"].get("c", 0)); scroll("fa2", eio((t - 34.4) / .9) * st["y"].get("a", 0))
            if t >= SYNC - .05: ev("fc", STEP_JS % (1 + min(1, max(0, (t - SYNC) / 1.4)), json.dumps(LABELS)))
        if 47.95 <= t < 57.2: scroll("fa2", eio((t - 55.2) / 1.0) * 1100 if t >= 55.2 else 0)
        if AI_BTN_IN <= t < 57.2:
            if t < TAP_RECOGNIZE: s = {"o": ease((t - AI_BTN_IN) / .4), "mode": "idle", "text": "Распознать по фото"}
            elif t < SCAN_TO: s = {"o": 1, "mode": "go", "x": ((t - SCAN_FROM) / (SCAN_TO - SCAN_FROM)) * 160 - 20, "text": "Распознаю…"}
            elif t < DONE_AT: s = {"o": 1, "mode": "go", "x": ((t - SCAN_TO) / (DONE_AT - SCAN_TO)) * 160 - 20, "text": "Заполняю поля…"}
            else: s = {"o": 1, "mode": "done", "text": "Готово: бренд, модель, размер"}
            ev("fa2", AIBTN % json.dumps(s))
        if TYPE_FROM <= t <= TYPE_TO + .25:
            k = (t - TYPE_FROM) / (TYPE_TO - TYPE_FROM); js = ""
            for (ph, text), (a, bb) in zip(TYPE, [(0, .15), (.15, .85), (.85, 1.0)]):
                n = int(len(text) * clamp((k - a) / (bb - a)) + 1e-4) if k > a else 0
                js += (f"var e=document.querySelector('input[placeholder=\"{ph}\"]');if(e){{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;"
                       f"if(e.value!=={json.dumps(text[:n])}){{s.call(e,{json.dumps(text[:n])});e.dispatchEvent(new Event('input',{{bubbles:true}}))}}}}")
            ev("fa2", js)

        page.evaluate(f"setT({t},{{}})")   # place phones/laptop first, so overlay boxes are measured at this frame's positions
        extra = {"rings": [], "callouts": []}
        # scan box over the uploaded photo
        if SCAN_FROM <= t < SCAN_TO + .3:
            bx = box("fa2", rect_of("img[alt='Фото']"))
            if bx:
                o = clamp((t - SCAN_FROM) / .2) * clamp((SCAN_TO + .3 - t) / .3)
                extra["scan"] = {"x": bx[0] - 6, "y": bx[1] - 6, "w": bx[2] + 12, "h": bx[3] + 12, "o": o, "k": (((t - SCAN_FROM) / .7) % 1)}
        # shipment: ring on the photo (shutter) and on the track number (stamp)
        if SHUTTER <= t < SHUTTER + 1.0:
            bx = box("fc", rect_of(".card img, img"))
            if bx: extra["rings"].append({"x": bx[0] - 8, "y": bx[1] - 8, "w": bx[2] + 16, "h": bx[3] + 16, "o": clamp((t - SHUTTER) / .15) * clamp((SHUTTER + 1.0 - t) / .3), "g": True})
        if STAMP <= t < STAMP + 1.2:
            bx = union("fc", f"{DT('Трек-номер')},{DT('Трек-номер')}&&{DT('Трек-номер')}.nextElementSibling")
            if bx: extra["rings"].append({"x": bx[0] - 10, "y": bx[1] - 8, "w": bx[2] + 20, "h": bx[3] + 16, "o": clamp((t - STAMP) / .12) * clamp((STAMP + 1.2 - t) / .3)})
        # comparison highlights (rings stay, only the latest callout is shown)
        if HL[0][0] <= t < 47.6:
            if not st["hl"] and t >= HL[0][0] - .05 and t >= 35.4:
                st["hl"] = {
                    "client-price": box("fc", "const e=[...document.querySelectorAll('.card')].find(x=>x.textContent.includes('Цена'));if(!e)return null;const r=e.getBoundingClientRect();return [r.left,r.top,r.width,Math.min(r.height,96)]"),
                    "admin-profit": union("fa2", f"{DT('Закупка')},{DT('Прибыль')}&&{DT('Прибыль')}.nextElementSibling"),
                    "admin-private": union("fa2", f"{DT('Ссылка')},{DT('Ссылка')}&&{DT('Ссылка')}.nextElementSibling,document.querySelector('.banner.info')"),
                    "admin-buttons": union("fa2", "...[...document.querySelectorAll('button')].filter(x=>['На склад','В отправку','Перезаказ','Отменить'].some(s=>x.textContent.includes(s)))"),
                }
            texts = {"client-price": ("Клиент видит только цену", False), "admin-profit": ("Закупка и прибыль: только у вас", True),
                     "admin-private": ("Ссылка и заметка: клиент не видит", False), "admin-buttons": ("Управление заказом", False)}
            fade_all = clamp((44.2 - t) / .3)
            for k_, (ht, name) in enumerate(HL):
                bx = st["hl"].get(name)
                if not bx or t < ht or t >= 44.2: continue
                o = clamp((t - ht) / .25) * fade_all
                g = name == "admin-profit"
                extra["rings"].append({"x": bx[0] - 8, "y": bx[1] - 8, "w": bx[2] + 16, "h": bx[3] + 16, "o": o, "g": g})
                nxt = HL[k_ + 1][0] if k_ + 1 < len(HL) else 44.2
                co = o * clamp((nxt - t) / .25) if name != "client-price" else o * clamp((40.3 - t) / .25)
                cx = 273 if name == "client-price" else 807
                extra["callouts"].append({"x": cx, "y": 1668, "text": texts[name][0], "o": co, "g": g, "ax": -50})
            if t >= SYNC - .2:
                bx = box("fc", rect_of(".stepper"))
                if bx:
                    o = clamp((t - SYNC + .2) / .25) * clamp((47.5 - t) / .3)
                    extra["rings"].append({"x": bx[0] - 8, "y": bx[1] - 8, "w": bx[2] + 16, "h": bx[3] + 16, "o": o, "g": True})
                    extra["callouts"].append({"x": 273, "y": 1668, "text": "Клиент видит сразу", "o": o, "g": True, "ax": -50})
        if st["tap"] and 0 <= t - st["tap"][0] <= .5:
            extra["tap"] = {"k": (t - st["tap"][0]) / .5, "x": st["tap"][1], "y": st["tap"][2]}
        page.evaluate(f"setT({t},{json.dumps(extra)})")
        name = f"still-{t:05.2f}.jpg" if only else f"f{i:04d}.jpg"
        page.screenshot(path=str(OUT / name), type="jpeg", quality=93)
        if i % 60 == 0: print("frame", i, f"t={t:.1f}", flush=True)
    b.close()
