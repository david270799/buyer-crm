import numpy as np, wave
from timeline import *
SR = 44100; N = int(DURATION * SR) + SR; t = np.arange(N) / SR
rng = np.random.default_rng(7)
def env_ar(n, a, r):
    e = np.ones(n); a = int(a*SR); r = int(r*SR)
    if a: e[:a] = np.linspace(0, 1, a)**2
    if r: e[-r:] *= np.linspace(1, 0, r)**2
    return e
def mix(buf, x, start, gain=1.0, pan=0.0):
    i = int(start*SR); x = x[:max(0, len(buf)-i)]
    buf[i:i+len(x), 0] += x*gain*(1-max(0,pan)); buf[i:i+len(x), 1] += x*gain*(1+min(0,pan))
mid = lambda n: 440*2**((n-69)/12)
L = np.zeros((N, 2))
# chords (Cmaj7 - Am7 - Fmaj7 - G6), 5.2 s each
CH = [[48,55,64,71],[45,52,60,67],[41,53,60,69],[43,55,62,69]]
bar = 5.2
for k in range(int(DURATION // bar) + 1):
    ch = CH[k % 4]; st = k*bar; n = int((bar+2.2)*SR)
    pad = np.zeros(n); tt = np.arange(n)/SR
    for note in ch:
        f = mid(note+12)
        for dt in (-.07, 0, .07):
            pad += np.sin(2*np.pi*f*(1+dt*.01)*tt + rng.random()*6) * .5
        pad += np.sin(2*np.pi*f*2*tt) * .06
    pad *= env_ar(n, 1.6, 2.2) * .028
    mix(L, pad, st, 1, 0)
    sub = np.sin(2*np.pi*mid(ch[0]-12)*tt) * env_ar(n, .4, 1.8) * .16
    mix(L, sub, st, 1)
    # soft plucks, 8th notes at 92 bpm
    step = 60/92/2
    arp = [ch[0]+24, ch[1]+24, ch[2]+12, ch[3]+12, ch[2]+24, ch[1]+24]
    j = 0; tm = st + .4
    while tm < st + bar - .2 and tm < DURATION - 1.5:
        nn = arp[j % len(arp)]; j += 1
        d = int(1.1*SR); x = np.arange(d)/SR
        p = (np.sin(2*np.pi*mid(nn)*x) + .35*np.sin(2*np.pi*mid(nn)*2*x)*np.exp(-x*9)) * np.exp(-x*5.5)
        p *= env_ar(d, .004, .05) * .05
        mix(L, p, tm, 1, (-1)**j*.35); tm += step*(1.5 if j % 3 == 0 else 1)
# soft taps: tiny low blip + filtered click
for tp, _name in TAPS:
    d = int(.22*SR); x = np.arange(d)/SR
    blip = np.sin(2*np.pi*(520*np.exp(-x*14)+200)*x) * np.exp(-x*22) * .16
    click = rng.standard_normal(d) * np.exp(-x*140) * .03
    click = np.convolve(click, np.ones(6)/6, mode="same")
    mix(L, blip + click, tp, 1)
# scene transitions: very quiet breath swell
for c in CUTS:
    d = int(1.1*SR); x = np.arange(d)/SR
    nz = rng.standard_normal(d); nz = np.convolve(nz, np.ones(60)/60, mode="same")
    sw = nz * np.sin(np.pi*np.clip(x/1.1, 0, 1))**2 * .05
    mix(L, sw, c-.5, 1)
# AI recognition: soft rising sparkle, typing ticks, success chime
d = int(1.3*SR); x = np.arange(d)/SR
for k_, n_ in enumerate([84, 88, 91, 95, 100]):
    b = np.sin(2*np.pi*mid(n_)*x[:int(.6*SR)])*np.exp(-x[:int(.6*SR)]*5)
    mix(L, b*.022*env_ar(len(b), .002, .1), SPARKLE + .12*k_, 1, (-1)**k_*.4)
tt_ = TYPE_FROM
while tt_ < TYPE_TO:
    dd = int(.05*SR); xx = np.arange(dd)/SR
    kk = np.convolve(rng.standard_normal(dd)*np.exp(-xx*160), np.ones(5)/5, mode="same")*.05
    mix(L, kk, tt_, 1, rng.uniform(-.2, .2)); tt_ += .1 + rng.uniform(0, .05)
for n_, off in [(91, 0), (96, .1)]:
    dd = int(1.4*SR); xx = np.arange(dd)/SR
    mix(L, np.sin(2*np.pi*mid(n_)*xx)*np.exp(-xx*3.2)*.05*env_ar(dd, .003, .1), DONE_AT + off, 1, .1)
# end chime (Cmaj9 bell)
for n_, off, g in [(84,0,.05),(88,.12,.04),(91,.24,.035),(95,.4,.03)]:
    d = int(3.2*SR); x = np.arange(d)/SR
    b = (np.sin(2*np.pi*mid(n_)*x)+.4*np.sin(2*np.pi*mid(n_)*2.76*x)*np.exp(-x*3)) * np.exp(-x*1.7)
    mix(L, b*g*env_ar(d,.003,.2), CHIME+off, 1, .2)
# reverb: synthetic IR
ir_n = int(1.8*SR); irx = np.arange(ir_n)/SR
ir = rng.standard_normal((ir_n, 2)) * np.exp(-irx*2.6)[:, None]
ir[:int(.02*SR)] = 0
def fftconv(a, b):
    n = len(a)+len(b)-1; m = 1 << (n-1).bit_length()
    return np.fft.irfft(np.fft.rfft(a, m)*np.fft.rfft(b, m), m)[:len(a)]
wet = np.stack([fftconv(L[:, c], ir[:, c]) for c in range(2)], 1) * .09
out = L + wet
# gentle lowpass for warmth
k = np.ones(3)/3; out = np.stack([np.convolve(out[:, c], k, mode="same") for c in range(2)], 1)
out = out[:int(DURATION*SR)]
fi = int(.8*SR); fo = int(1.6*SR)
out[:fi] *= np.linspace(0, 1, fi)[:, None]**2; out[-fo:] *= np.linspace(1, 0, fo)[:, None]**2
out *= .72/np.max(np.abs(out))
pcm = (out*32767).astype("<i2")
with wave.open("audio.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
print("audio ok", len(out)/SR)
