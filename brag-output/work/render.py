import sys, json, pathlib
from playwright.sync_api import sync_playwright
from timeline import *

OUT = pathlib.Path("frames"); OUT.mkdir(exist_ok=True)
STAGE = pathlib.Path("stage.html").read_text()
ASSETS = pathlib.Path("assets").resolve()
only = [float(a) for a in sys.argv[1:]]
ease = lambda x: 1 - (1 - min(1, max(0, x))) ** 3
eio = lambda x: (lambda x: 4*x**3 if x < .5 else 1-(-2*x+2)**3/2)(min(1, max(0, x)))
LABELS = {0: ("new", "Новый"), 1: ("bought", "Выкуплен"), 2: ("warehouse", "На складе"), 3: ("cargo", "Отправлен"), 4: ("delivered", "Доставлен")}
# frame → (stage x, stage y, scale) of its viewport
MAP = {"fa": (90, 520, 2.3077), "fc": (90, 520, 2.3077), "fc2": (30, 640, 1.282), "fa2": (550, 640, 1.282), "fd": (40, 624, .78125)}

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1080, "height": 1920}, device_scale_factor=1, locale="ru-RU", timezone_id="Asia/Seoul", color_scheme="light")
    ctx.add_init_script("""(()=>{const role=(/^(fa|fd)/.test(window.name))?'admin':'client';const o=Storage.prototype.getItem;Storage.prototype.getItem=function(k){return k==='crm-demo-role'?role:o.call(this,k)}})()""")
    ctx.route(lambda u: not (u.startswith("http://localhost:8080") or u.startswith("http://127.0.0.1:8080") or u.startswith("data:") or u.startswith("blob:")), lambda r: r.abort())
    page = ctx.new_page()
    page.route("http://localhost:8080/__stage.html", lambda r: r.fulfill(body=STAGE, content_type="text/html; charset=utf-8"))
    page.route("http://localhost:8080/__assets/*", lambda r: r.fulfill(path=str(ASSETS / r.request.url.split("/")[-1])))
    page.goto("http://localhost:8080/__stage.html", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    F = {n: page.frame(name=n) for n in MAP}
    ev = lambda n, js: F[n].evaluate(f"(()=>{{{js}}})()")
    def nav(n, h, wait=900):
        ev(n, f"location.hash={json.dumps(h)}"); page.wait_for_timeout(wait)
    def top_of(n, sel):
        return ev(n, f"const e=document.querySelector({json.dumps(sel)});return e?e.getBoundingClientRect().top+scrollY:0") or 0
    def center(n, sel):
        c = ev(n, f"const e=document.querySelector({json.dumps(sel)});if(!e)return null;const r=e.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]")
        if not c: return None
        x0, y0, s = MAP[n]; return (x0 + c[0]*s, y0 + c[1]*s)
    scroll = lambda n, y: ev(n, f"scrollTo(0,{y})")

    # stepper/badge overlay: deterministic function of p (0..4)
    STEP_JS = """const p=%s;
      let st=document.getElementById('vstyle');if(!st){st=document.createElement('style');st.id='vstyle';st.textContent='.step::before{background:linear-gradient(90deg,var(--accent) calc(var(--f,0)*100%%),var(--surface-3) 0)!important}.step .icon{transition:none!important}.step.current .icon{box-shadow:none!important}';document.head.appendChild(st)}
      [...document.querySelectorAll('.stepper .step')].forEach((s,i)=>{
        s.classList.remove('done','current');if(p>=i)s.classList.add('done');
        s.style.setProperty('--f',Math.min(1,Math.max(0,p-(i-1))));
        const ic=s.querySelector('.icon');const k=p>=i?Math.max(0,1-(p-i)/.4):0;
        ic.style.transform='scale('+(1+.22*Math.sin(k*Math.PI))+')';
        ic.style.boxShadow=(p>=i&&p<i+1)?'0 0 0 4px var(--accent-soft)':'none';
        const w=s.querySelector('.when');if(w)w.style.opacity=p>=i+.3?1:0;
      });
      const bd=document.querySelector('.badge');if(bd){const m=%s;const k=Math.min(4,Math.floor(p+.02));bd.className='badge s-'+m[k][0];bd.textContent=m[k][1]}"""
    def stepper(n, pv):
        ev(n, STEP_JS % (pv, json.dumps({str(k): v for k, v in LABELS.items()})))

    st = {"done": set(), "tap": None, "y": {}}
    def once(key):
        if key in st["done"]: return False
        st["done"].add(key); return True
    def tap_at(t0, n, sel):
        c = center(n, sel)
        if c: st["tap"] = (t0, c[0], c[1])

    TYPE = [("Nike", "On"), ("Air Max 95", "Cloud 5 Waterproof"), ("270", "270")]   # (placeholder, text)
    def typing(t):
        k = (t - TYPE_FROM) / (TYPE_TO - TYPE_FROM)
        parts = [(0, .25), (.25, .85), (.85, 1.0)]
        js = ""
        for (ph, text), (a, bb) in zip(TYPE, parts):
            n = int(len(text) * min(1, max(0, (k - a) / (bb - a))) + .0001) if k > a else 0
            js += f"const e=document.querySelector('input[placeholder=\"{ph}\"]');"
            js += f"if(e){{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;if(e.value!=={json.dumps(text[:n])}){{s.call(e,{json.dumps(text[:n])});e.dispatchEvent(new Event('input',{{bubbles:true}}))}}}};"
        return js.replace("const e=", "var e=")
    AIBTN = """let b=document.getElementById('aibtn');
      if(!b){const f=[...document.querySelectorAll('.field')].find(x=>x.textContent.trim().startsWith('Бренд'));if(!f)return;
        b=document.createElement('button');b.id='aibtn';b.className='btn';b.type='button';
        b.style.cssText='width:100%%;justify-content:center;margin:2px 0 10px;gap:8px;position:relative;overflow:hidden;height:46px';f.parentNode.insertBefore(b,f)}
      const s=%s;
      const spark='<svg width=\"18\" height=\"18\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z\"/><path d=\"M19 16l.7 1.8L21.5 18.5l-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z\"/></svg>';
      b.style.display=s.o>0?'inline-flex':'none';b.style.opacity=s.o;
      b.innerHTML=(s.mode==='go'?'<span style=\"position:absolute;inset:0;background:linear-gradient(100deg,transparent '+(s.x-30)+'%%,rgba(120,150,200,.35) '+s.x+'%%,transparent '+(s.x+30)+'%%)\"></span>':'')+spark+'<span style=\"position:relative\">'+s.text+'</span>';"""
    def aibtn(t):
        if t < 12.2: return
        o = ease((t - 12.2) / .4)
        if t < 13.2: s = {"o": o, "mode": "idle", "text": "Распознать по фото"}
        elif t < 14.4: s = {"o": 1, "mode": "go", "x": ((t - 13.2) / 1.2) * 160 - 20, "text": "Распознаю…"}
        else: s = {"o": 1, "mode": "idle", "text": "Распознано"}
        ev("fa", AIBTN % json.dumps(s))

    times = only or [i / FPS for i in range(int(DURATION * FPS))]
    for i, t in enumerate(times):
        # --- one-shot events, in order ---
        if t >= 6.6 and once("botbtn"): st["tap"] = (6.6, 90 + 195*2.3077, 520 + 197*2.3077)   # inline "Открыть CRM" button inside the mock chat
        if t >= 9.4 and once("t2"):
            tap_at(9.4, "fa", ".btn.primary")
        if t >= 9.5 and once("n2"): nav("fa", "#/orders/new", 1200)
        if t >= 11.0 and once("t3"):
            c = center("fa", "label.btn")
            if c: st["tap"] = (11.0, c[0], c[1])
        if t >= 11.1 and once("upload"):
            page.frame_locator("#fa").locator("input[type=file]").first.set_input_files(str(ASSETS / "1.jpg")); page.wait_for_timeout(1800)
        if t >= 13.2 and once("t4"):
            c = center("fa", "#aibtn")
            if c: st["tap"] = (13.2, c[0], c[1])
        if t >= 18.9 and once("t5"):
            c = center("fa", ".actions .btn.primary")
            if c: st["tap"] = (18.9, c[0], c[1])
        if t >= 19.3 and once("pre-c"): pass
        if t >= 21.0 and once("t6"): tap_at(21.0, "fc", '.tabbar a[href="#/orders"]')
        if t >= 21.1 and once("n6"): nav("fc", "#/orders"); st["y"]["n1"] = max(0, top_of("fc", 'a[href="#/orders/N1"]') - 260)
        if t >= 22.9 and once("t7"): tap_at(22.9, "fc", 'a[href="#/orders/N1"]')
        if t >= 23.0 and once("n7"): nav("fc", "#/orders/N1", 1000); st["y"]["st1"] = max(0, top_of("fc", ".stepper") - 330)
        if t >= 27.6 and once("t8"): tap_at(27.6, "fc", '.tabbar a[href="#/balance"]')
        if t >= 27.7 and once("n8"): nav("fc", "#/balance")
        if t >= 31.6 and once("t9"): tap_at(31.6, "fc", '.tabbar a[href="#/shipments"]')
        if t >= 31.7 and once("n9"): nav("fc", "#/shipments")
        if t >= 33.2 and once("t10"): tap_at(33.2, "fc", 'a[href^="#/shipments/"]')
        if t >= 33.3 and once("n10"):
            h = ev("fc", "const e=document.querySelector('a[href^=\"#/shipments/\"]');return e?e.getAttribute('href'):null")
            if h: nav("fc", h, 1000)
        if t >= 36.0 and once("prep6"):
            st["y"]["st5"] = max(0, top_of("fc2", ".stepper") - 220); st["y"]["adm5"] = max(0, top_of("fa2", "h3") - 140)
        if t >= 42.3 and once("t11"):
            c = None
            for lab in ("На склад",):
                c = ev("fa2", f"const e=[...document.querySelectorAll('button')].find(x=>x.textContent.includes({json.dumps(lab)}));if(!e)return null;const r=e.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]")
            if c: st["tap"] = (42.3, MAP["fa2"][0] + c[0]*MAP["fa2"][2], MAP["fa2"][1] + c[1]*MAP["fa2"][2])
        if t >= 42.4 and once("click11"):
            ev("fa2", "const e=[...document.querySelectorAll('button')].find(x=>x.textContent.includes('На склад'));if(e)e.click()"); page.wait_for_timeout(900)
        if t >= 50.8 and once("t12"): tap_at(50.8, "fd", 'aside a[href="#/"]')
        if t >= 50.9 and once("n12"): nav("fd", "#/", 1000)

        # --- per-frame, time-only state ---
        if t < 19.2:
            if 9.5 <= t < 17: scroll("fa", 0)
            elif t >= 17: scroll("fa", eio((t - 17.0) / 1.8) * 1100)
        if 12.2 <= t < 19.2: aibtn(t)
        if TYPE_FROM <= t <= TYPE_TO + .2 or (t > TYPE_TO and once("typefinal")): ev("fa", typing(min(t, TYPE_TO + .1)))
        if 19.2 <= t < 31.2:
            if t < 21.1: scroll("fc", eio((t - 19.6) / 1.4) * 260)
            elif t < 23.0: scroll("fc", eio((t - 21.6) / 1.2) * st["y"].get("n1", 0))
            elif t < 27.7: scroll("fc", eio((t - 23.3) / .8) * st["y"].get("st1", 0))
            elif t < 31.2: scroll("fc", eio((t - 28.3) / 2.6) * 520)
            if 23.1 <= t < 27.6: stepper("fc", 0 if t < 23.6 else min(4, max(0, (t - 23.6) / 3.6 * 4)))
        if 31.2 <= t < 36.2:
            if 33.4 <= t: scroll("fc", eio((t - 34.0) / 1.6) * 260)
            else: scroll("fc", 0)
        if 36.0 <= t < 48.4:
            scroll("fc2", eio((t - 36.8) / 1.2) * st["y"].get("st5", 0)); scroll("fa2", eio((t - 37.2) / 1.4) * st["y"].get("adm5", 0))
            if t >= 42.5: stepper("fc2", 1 + min(1, (t - 42.5) / 1.4))
        # highlight ring on admin purchase/profit block
        ring = None
        if 39.2 <= t < 42.0:
            r = ev("fa2", "const e=[...document.querySelectorAll('dl.kv')].find(d=>d.parentElement.textContent.includes('Для администратора'));if(!e)return null;const r=e.getBoundingClientRect();return [r.left,r.top,r.width,r.height]")
            if r:
                x0, y0, s = MAP["fa2"]; o = min(1, (t - 39.2) / .4) * min(1, (42.0 - t) / .3)
                ring = {"o": o, "x": x0 + r[0]*s - 8, "y": y0 + r[1]*s - 8, "w": r[2]*s + 16, "h": r[3]*s + 16}
        tp = None
        if st["tap"] and 0 <= t - st["tap"][0] <= .5:
            tp = {"k": (t - st["tap"][0]) / .5, "x": st["tap"][1], "y": st["tap"][2]}
        page.evaluate(f"setT({t},{json.dumps(tp)},{json.dumps(ring)})")
        name = f"still-{t:05.2f}.jpg" if only else f"f{i:04d}.jpg"
        page.screenshot(path=str(OUT / name), type="jpeg", quality=93)
        if i % 60 == 0: print("frame", i, f"t={t:.1f}", flush=True)
    b.close()
