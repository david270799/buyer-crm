"""All timings of video v3 (seconds). Shared by render.py (picture) and audio.py (sound)."""
FPS = 30
DURATION = 75.0

# scene starts
S1, S2, S3, S4, S5, S6, S7, S8, S9, S10 = 0, 7, 12, 19, 26, 34, 48, 57, 63, 68

# scene 1: chat, then chaos
MSG = [0.5, 1.1, 1.7, 2.5]                 # incoming bubbles in the chat (2.5 = admin's Excel screenshot)
CHAOS_FROM, CHAOS_TO = 3.3, 6.3            # flood of questions
CHAOS_N = 46                               # bubbles in the flood (accelerating)
GLITCH, FLASH = 6.3, 6.65                  # glitch, white flash; everything clean at 6.9

def chaos_times():
    # accelerating: dense at the end
    return [CHAOS_FROM + (CHAOS_TO - CHAOS_FROM) * (i / CHAOS_N) ** 0.6 for i in range(CHAOS_N)]

# scene 2: bot → "Открыть CRM" → sheet slides up → loading → dashboard
BOT_MSG = 7.6
TAP_OPEN = 8.8
SHEET_FROM, SHEET_TO = 9.0, 9.55
LOAD_FROM, LOAD_TO = 9.55, 10.45

# pains: flashback bubble (with strike) over the app
FLASH_BACKS = [(12.0, "Какой у меня баланс?"), (19.0, "Вы отправили? Какой трек?"), (26.0, "Заказ уже выкуплен?")]
FB_LEN = 1.45
CASH = 13.6
SHIP_TAP, SHUTTER, STAMP = 21.3, 21.75, 22.7
PILLS = [(28.0, "Новые"), (29.5, "Выкуплены"), (31.0, "Склад"), (32.5, "Карго")]

# scene 6: comparison
HL = [(37.0, "client-price"), (38.3, "admin-profit"), (40.4, "admin-private"), (42.6, "admin-buttons")]
TAP_WAREHOUSE = 44.4
SYNC = 44.7                                 # client stepper moves 1 → 2 (44.7 .. 46.1)

# scene 7: AI
TAP_ADD_PHOTO, UPLOAD = 49.6, 49.7
AI_BTN_IN = 50.5
TAP_RECOGNIZE = 51.4
SCAN_FROM, SCAN_TO = 51.4, 52.8
TYPE_FROM, TYPE_TO = 52.8, 54.8
DONE_AT = 55.0
TAP_CREATE = 56.5

# scene 8: laptop
DESK_TAPS = [(59.8, "Склад"), (61.4, "Все")]

# scene 9: chips
CHIPS = [63.7 + i * 0.42 for i in range(5)]

# scene 10
IMPACT = 68.3

# scrolls (for the rustle sound): (from, to)
SCROLLS = [(14.6, 17.8), (23.2, 25.4), (55.2, 56.2)]

# every tap ring (time, label) — used by audio for clicks
TAPS = [(TAP_OPEN, "open"), (SHIP_TAP, "ship"), *PILLS, (TAP_WAREHOUSE, "warehouse"), (TAP_ADD_PHOTO, "photo"),
        (TAP_RECOGNIZE, "ai"), (TAP_CREATE, "create"), *DESK_TAPS]

# whooshes on scene changes / big moves
WHOOSH = [S3 + .0, S4, S5, S6, S7, S8, S9]
