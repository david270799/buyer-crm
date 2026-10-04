"""Soundtrack v3: synthesised beat + one sound effect per on-screen action (timings from timeline.py)."""
import numpy as np, wave
from timeline import *

SR = 44100
N = int((DURATION + 1) * SR)
rng = np.random.default_rng(11)
music = np.zeros((N, 2)); sfx = np.zeros((N, 2))
mid = lambda n: 440 * 2 ** ((n - 69) / 12)
tt = lambda d: np.arange(int(d * SR)) / SR

def put(buf, x, at, g=1.0, pan=0.0):
    i = int(at * SR)
    if i >= len(buf) or i + len(x) <= 0: return
    x = x[:len(buf) - i]
    l, r = np.sqrt(.5 * (1 - pan)), np.sqrt(.5 * (1 + pan))
    buf[i:i + len(x), 0] += x * g * l * 1.414; buf[i:i + len(x), 1] += x * g * r * 1.414

def band(x, lo, hi):  # FFT band-pass with soft edges
    n = len(x); f = np.fft.rfftfreq(n, 1 / SR); X = np.fft.rfft(x)
    m = np.clip((f - lo * .7) / (lo * .3 + 1), 0, 1) * np.clip((hi * 1.3 - f) / (hi * .3), 0, 1)
    return np.fft.irfft(X * m, n)

def env(n, a, d):  # attack, exponential decay (seconds)
    t = np.arange(n) / SR; e = np.exp(-t / max(d, 1e-4))
    if a > 0: e *= np.clip(t / a, 0, 1)
    return e
noise = lambda d: rng.standard_normal(int(d * SR))

# ---------------- drums & bass ----------------
def kick():
    t = tt(.45); f = 48 + 110 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7.5) + .3 * band(noise(.45), 1000, 5000) * np.exp(-t * 90)
def clap():
    t = tt(.3); n = band(noise(.3), 900, 6000)
    e = sum(np.exp(-np.clip(t - o, 0, None) * 60) * (t >= o) for o in (0, .011, .022)) * .6 + np.exp(-t * 18) * .5
    return n * e
def hat(open_=False):
    t = tt(.25 if open_ else .06); return band(noise(len(t) / SR), 7000, 16000) * np.exp(-t * (14 if open_ else 70))
def sub(note, d):
    t = tt(d); f = mid(note)
    x = np.sin(2 * np.pi * f * t) + .25 * np.sin(2 * np.pi * 2 * f * t)
    return np.tanh(1.6 * x) * env(len(t), .005, d * .7) * np.clip((d - t) / .05, 0, 1)
K, C, HC, HO = kick(), clap(), hat(), hat(True)

BPM = 112; beat = 60 / BPM; bar = 4 * beat
PROG = [(57, [57, 60, 64]), (53, [53, 57, 60]), (48, [48, 52, 55]), (55, [55, 59, 62])]   # Am F C G
BEAT_FROM, BEAT_TO = 7.2, 67.9
kicks = []
b = 0
while BEAT_FROM + b * bar < BEAT_TO:
    t0 = BEAT_FROM + b * bar; root, ch = PROG[b % 4]
    busy = 34 <= t0 < 48                       # comparison: denser groove
    for k in range(4):
        tb = t0 + k * beat
        if tb >= BEAT_TO: break
        if k in (0, 2) or (k == 3 and b % 2 == 1): put(music, K, tb, .9); kicks.append(tb)
        if k in (1, 3): put(music, C, tb, .45, .05)
        for h in range(2 if not busy else 4):
            th = tb + h * beat / (2 if not busy else 4)
            put(music, HO if (h == 1 and k == 3 and not busy) else HC, th, .16 if h % 2 else .22, .3 if h % 2 else -.2)
        # bass: root on 1, octave pickup on "and of 4"
    put(music, sub(root - 12, beat * 1.8), t0, .55); put(music, sub(root - 12, beat * .9), t0 + 2 * beat, .45)
    put(music, sub(root, beat * .45), t0 + 3.5 * beat, .3)
    b += 1

# pads (whole video, ducked by kicks)
pad = np.zeros((N, 2)); b = 0; t0 = 0.0
while t0 < DURATION:
    root, ch = PROG[b % 4]; d = bar + .6; t = tt(d)
    x = sum(np.sin(2 * np.pi * mid(n + 12) * (1 + dt) * t + rng.random() * 6) for n in ch for dt in (-.003, 0, .003))
    x = x * np.clip(t / .5, 0, 1) * np.clip((d - t) / .6, 0, 1) * .035
    put(pad, x, t0, 1, (-1) ** b * .2); t0 += bar; b += 1
duck = np.ones(N)
for kt in kicks:
    i = int(kt * SR); n = int(.3 * SR); duck[i:i + n] = np.minimum(duck[i:i + n], 1 - .55 * np.exp(-np.arange(min(n, N - i)) / SR / .09))
pad *= duck[:, None]
# intro: pad quieter under the chaos, drone riser
pad[:int(7 * SR)] *= np.linspace(.4, .9, int(7 * SR))[:, None]
music += pad

# ---------------- sound effects ----------------
def msg(p=0):  # notification "ding-ding"
    t = tt(.35); a = np.sin(2 * np.pi * (1318 * 2 ** (p / 12)) * t) * np.exp(-t * 18)
    t2 = tt(.4); b_ = np.sin(2 * np.pi * (1760 * 2 ** (p / 12)) * t2) * np.exp(-t2 * 14)
    out = np.zeros(int(.5 * SR)); out[:len(a)] += a; o = int(.08 * SR); out[o:o + len(b_)] += b_ * .8
    return out
def click():
    t = tt(.05); return band(noise(.05), 2000, 9000) * np.exp(-t * 260) * .8 + np.sin(2 * np.pi * 1900 * t) * np.exp(-t * 160) * .5
def whoosh(d=.7, lo=300, hi=4000):
    t = tt(d); n = band(noise(d), lo, hi); e = np.sin(np.pi * np.clip(t / d, 0, 1)) ** 2
    return n * e
def pop():
    t = tt(.12); f = 280 + 900 * (1 - np.exp(-t * 40)); return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 32)
def bell(freqs, d=1.2, dec=3.0):
    t = tt(d); return sum(a * np.sin(2 * np.pi * f * t) * np.exp(-t * dec * (1 + i * .4)) for i, (f, a) in enumerate(freqs))
def ping(): return bell([(1568, 1), (2349, .5), (3136, .2)], .9, 4.5)
def keyclick():
    t = tt(.035); return band(noise(.035), 1500, 7000) * np.exp(-t * 200)

# scene 1: chat bubbles + chaos cacophony + riser + glitch + tape stop
for i, m in enumerate(MSG): put(sfx, msg(i % 3), m, .5, (-1) ** i * .2)
for i, ct in enumerate(chaos_times()):
    put(sfx, msg(rng.integers(-5, 7)), ct, .22 + .2 * i / CHAOS_N, rng.uniform(-.8, .8))
r = tt(CHAOS_TO - CHAOS_FROM + .3); riser = band(noise(len(r) / SR), 400, 9000) * (r / r[-1]) ** 2.2 * .5
riser += np.sin(2 * np.pi * np.cumsum(60 + 220 * (r / r[-1]) ** 2) / SR) * (r / r[-1]) ** 1.5 * .35   # rising hum
put(sfx, riser, CHAOS_FROM)
g = noise(.35); gt = tt(.35); g = band(g, 200, 6000) * (np.sign(np.sin(2 * np.pi * 23 * gt)) * .5 + .5)
put(sfx, g, GLITCH, .45)
for k in range(6): put(sfx, np.sin(2 * np.pi * 220 * 2 ** (rng.integers(0, 12) / 12) * tt(.05)) * .6, GLITCH + k * .05, .5)
ts = tt(.4); f = 330 * (1 - ts / .45) ** 2 + 20; put(sfx, np.tanh(3 * np.sin(2 * np.pi * np.cumsum(f) / SR)) * (1 - ts / .4) * .5, FLASH)   # tape stop
put(sfx, whoosh(.5, 200, 3000), FLASH - .1, .5)
# scene 2: drop + bot message + click + sheet swoosh + loading blips
t = tt(1.6); put(sfx, np.sin(2 * np.pi * np.cumsum(38 + 50 * np.exp(-t * 6)) / SR) * np.exp(-t * 2.2), BEAT_FROM, .9)   # deep drop
put(sfx, msg(2), BOT_MSG, .45)
for ti, _ in TAPS: put(sfx, click(), ti, .55)
put(sfx, whoosh(.6, 250, 5000), SHEET_FROM - .05, .55, -.2)
for k in range(3): put(sfx, np.sin(2 * np.pi * 880 * tt(.08)) * np.exp(-tt(.08) * 40), LOAD_FROM + .15 + k * .3, .2)
# pains: flashback in (rewind swoosh) + strike scratch
for a, _ in FLASH_BACKS:
    put(sfx, whoosh(.45, 600, 7000)[::-1], a - .2, .4)
    s = tt(.18); put(sfx, band(noise(.18), 1500, 8000) * np.sin(np.pi * s / .18), a + .55, .35)
    put(sfx, whoosh(.45, 300, 3000), a + 1.15, .35, .4)
# cash register + coins
put(sfx, bell([(2093, 1), (2794, .7), (3951, .4)], 1.4, 3.2), CASH, .45)
put(sfx, band(noise(.06), 2000, 8000) * np.exp(-tt(.06) * 80), CASH - .06, .4)
for k in range(7): put(sfx, np.sin(2 * np.pi * rng.uniform(3200, 5200) * tt(.18)) * np.exp(-tt(.18) * 30), CASH + .2 + k * .07 + rng.uniform(0, .03), .14, rng.uniform(-.6, .6))
# scroll rustle
for a, z in SCROLLS:
    d = z - a; t = tt(d); x = band(noise(d), 1200, 6000) * np.sin(np.pi * t / d) ** 1.5 * (0.6 + .4 * np.sin(2 * np.pi * 7 * t) ** 2)
    put(sfx, x, a, .12, .1)
# camera shutter + stamp
for o in (0, .07): put(sfx, band(noise(.04), 1500, 9000) * np.exp(-tt(.04) * 120), SHUTTER + o, .5)
t = tt(.35); put(sfx, np.sin(2 * np.pi * 85 * t) * np.exp(-t * 14) + .5 * band(noise(.35), 200, 2500) * np.exp(-t * 30), STAMP, .7)
# filter pills: juicy pops
for i, (pt, _) in enumerate(PILLS): put(sfx, pop(), pt, .45, (-1) ** i * .25)
# comparison: pings per highlight, magic on sync
for i, (ht, name) in enumerate(HL): put(sfx, ping() if name != "admin-profit" else bell([(1760, 1), (2637, .6)], .9, 4), ht, .32, -.35 if name == "client-price" else .35)
for k, n in enumerate([72, 76, 79, 84, 88, 91]):
    put(sfx, bell([(mid(n), 1), (mid(n) * 2, .3)], 1.0, 4), SYNC + k * .07, .16, -.5 + k * .2)
put(sfx, whoosh(1.0, 2000, 10000), SYNC - .1, .25)
# AI: scan sweep, typing, success
d = SCAN_TO - SCAN_FROM; t = tt(d); f = 500 + 1300 * t / d
put(sfx, np.sin(2 * np.pi * np.cumsum(f) / SR) * (0.5 + .5 * np.sin(2 * np.pi * 14 * t)) * np.sin(np.pi * t / d) * .5, SCAN_FROM, .35)
put(sfx, band(noise(d), 3000, 12000) * np.sin(np.pi * t / d) * .3, SCAN_FROM, .25)
tk = TYPE_FROM
while tk < TYPE_TO:
    put(sfx, keyclick(), tk, .35, rng.uniform(-.3, .3)); tk += .075 + rng.uniform(0, .04)
put(sfx, bell([(mid(88), 1), (mid(88) * 2, .25)], 1.2, 3), DONE_AT, .35)
put(sfx, bell([(mid(92), 1), (mid(92) * 2, .25)], 1.4, 2.6), DONE_AT + .12, .35)
# transitions, laptop, chips
for w in WHOOSH: put(sfx, whoosh(.7, 250, 4500), w - .3, .32, rng.uniform(-.4, .4))
put(sfx, whoosh(1.2, 120, 2500), S8 + .1, .45)
for i, ct in enumerate(CHIPS): put(sfx, pop(), ct + .05, .5, -.4 + i * .2)
# finale: impact + chord stab
t = tt(3.5); put(sfx, np.sin(2 * np.pi * np.cumsum(32 + 60 * np.exp(-t * 5)) / SR) * np.exp(-t * 1.1), IMPACT, 1.0)
put(sfx, band(noise(1.2), 60, 3000) * np.exp(-tt(1.2) * 4), IMPACT, .35)
fin = sum(np.sin(2 * np.pi * mid(n) * tt(6)) * np.exp(-tt(6) * .55) for n in (45, 57, 64, 69, 72, 76)) * .09
put(sfx, fin, IMPACT, 1)

# ---------------- mix ----------------
irn = int(1.4 * SR); ir = rng.standard_normal((irn, 2)) * np.exp(-np.arange(irn) / SR * 3.2)[:, None]; ir[:int(.015 * SR)] = 0
ir /= np.sqrt((ir ** 2).sum(0))[None, :]   # unit-energy impulse response
def conv(a, b_):
    n = len(a) + len(b_) - 1; m = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(a, m) * np.fft.rfft(b_, m), m)[:len(a)]
mix = music * .8 + sfx
import os
if os.environ.get("DBG"):
    for nm, bf in (("music", music), ("sfx", sfx), ("pad", pad)):
        rms = [float(np.sqrt(np.mean(bf[int(s*SR):int((s+1)*SR)]**2))) for s in range(0, 75, 5)]
        print(nm, [round(x, 3) for x in rms])
wet = np.stack([conv(mix[:, c], ir[:, c]) for c in range(2)], 1) * .22
out = np.tanh((mix + wet) * 1.1)[:int(DURATION * SR)]
fo = int(1.0 * SR); out[-fo:] *= np.linspace(1, 0, fo)[:, None] ** 2
out *= .89 / np.max(np.abs(out))
with wave.open("audio.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((out * 32767).astype("<i2").tobytes())
print("audio ok", len(out) / SR)
