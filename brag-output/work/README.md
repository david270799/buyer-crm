# Buyer CRM launch video — how it is made (re-runnable)

Current version: **final** (`../scenario-final.md` → `../brag-final.mp4`, 78 s, 2340 frames, poster = frame f1185, mux with `-af volume=-4.6dB` → about -16 LUFS). Filmed on the current app (main merged): shipment photo carousel, real AI icon next to «Бренд» (prepared answer from `video_server.py`, no Gemini key), «Моя прибыль». Previous: v3 (`../brag-v3.mp4`, 75 s).
The notes below were written for v2 and still apply; v3 differences: 10 orders, shipment photo `assets/11.jpg`, `restart.sh` keeps a PID file, full render takes ~13 min.

## v2 notes

Scenario: `../brag-plan-v2.md`. Output: `../brag-v2.mp4` (1080x1920, 30 fps, 62.6 s, Russian, music + soft sounds).
Order data = your 5 photos in `assets/` (On Cloud 5 Waterproof, adidas Sportswear Denim Track Top,
Nike Air Max Flyknit Bloom, Timex Expedition Scout, Represent Denim Track Jacket & Pants). Prices/sizes are demo values.

Everything is a deterministic script — a new session should RUN these, not re-invent them:

1. Setup (once): `cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt numpy playwright`;
   `cd web && npm ci && npm run build`.
2. `bash restart.sh`            starts the video data server (the real CRM services in demo mode with the video data set) on :8080.
3. `python render.py`           renders 1878 frames to `frames/` (drives 5 live app windows in headless Chromium; all external
   network requests are blocked; takes ~8 min). Pass times in seconds to render only those stills (`python render.py 13.8 41`).
   Restart the server before every full render: the video does one real click ("На склад") that changes data.
4. `python audio.py`            synthesises `audio.wav` (pads, taps, AI sparkle, typing ticks, chime) from `timeline.py`.
5. `ffmpeg -framerate 30 -i frames/f%04d.jpg -i audio.wav -af volume=-2dB -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -shortest brag-v2.mp4`
   (frame 0 is replaced by the poster frame f0111).

Note: the "Распознать по фото" button is a concept drawn into the real new-order form by `render.py` (AIBTN). It does not exist in the product.
Same for the smooth status animation on the order stepper (STEP_JS): the real app switches steps without animation.
`stage.html` holds the layout (captions, phones, browser window, chips, outro); `timeline.py` holds all timings.
