"""All timings of the final video (seconds). Shared by render.py (picture) and audio.py (sound)."""
FPS = 30
DURATION = 78.0

S1, S2, S3, S4, S5, S6, S7, S8, S9, S10 = 0, 7, 12, 20, 28, 36, 48, 57, 66, 71

# scene 1: chat, then chaos
MSG = [0.5, 1.1, 1.7, 2.5]
CHAOS_FROM, CHAOS_TO = 3.3, 6.3
CHAOS_N = 46
GLITCH, FLASH = 6.3, 6.65

def chaos_times():
    return [CHAOS_FROM + (CHAOS_TO - CHAOS_FROM) * (i / CHAOS_N) ** 0.6 for i in range(CHAOS_N)]

# scene 2: bot → "Открыть CRM" → sheet slides up → loading → client home
BOT_MSG = 7.6
TAP_OPEN = 8.8
SHEET_FROM, SHEET_TO = 9.0, 9.55
LOAD_FROM, LOAD_TO = 9.55, 10.45

# pain chats (scenes 3-5): client messages, admin file (scene 3), red cross, chat swipes away
PAIN = [
    {"from": 12.0, "msgs": [(12.3, "Какой у меня баланс?"), (12.8, "Сколько за что сняли?")], "file": 13.4, "cross": 14.2},
    {"from": 20.0, "msgs": [(20.3, "Вы уже отправили?"), (20.7, "Когда?"), (21.1, "Какой трек?"), (21.5, "Можно фото коробки?")], "file": None, "cross": 22.0},
    {"from": 28.0, "msgs": [(28.3, "Мои заказы выкупили?"), (28.7, "Он уже приехал к вам?"), (29.1, "В карго передали?")], "file": None, "cross": 29.6},
]
CROSS_LEN, OUT_AFTER, OUT_LEN = 0.4, 0.5, 0.4    # cross draws, then the chat swipes away

# scene 3
CASH = 15.3
# scene 4
SHIP_TAP = 23.6
SHUTTER1, SWIPE, SHUTTER2, STAMP = 24.1, 24.6, 25.0, 25.4
# scene 5
PILLS = [(31.2, "Новые"), (32.4, "Выкуплены"), (33.6, "Склад"), (34.8, "Карго")]

# scene 6: comparison
HL = [(37.6, "client-price"), (38.6, "admin-profit"), (40.0, "admin-buttons")]
TAP_WAREHOUSE = 41.3
SYNC = 41.6                     # client stepper moves 1 → 2 (41.6 .. 43.0)
TAP_TABS = 44.3                 # both phones → «Заказы»
HL_LIST = 45.0                  # client card price vs admin «закупка»

# scene 7: AI (real icon next to «Бренд»; prepared answer, no Gemini key here)
TAP_ADD_PHOTO, UPLOAD = 49.6, 49.7
TAP_AI = 50.8
SCAN_FROM, SCAN_TO = 50.8, 52.2  # the real click happens at SCAN_TO, fields fill
DONE_AT = 52.4
TAP_CREATE = 55.6

# scene 8: laptop
DESK_PROFIT_HL = 58.6
DESK_SHIPMENTS = 60.0
DESK_DASH = 61.3
ZOOM_FROM, ZOOM_TO = 61.6, 66.0      # stays on the dashboard profit until the scene ends
COUNT_FROM, COUNT_TO = 61.8, 63.4

# scene 9
CHIPS = [66.7 + i * 0.42 for i in range(5)]
# scene 10
IMPACT = 71.3

SCROLLS = [(16.2, 19.4), (25.9, 27.6), (53.6, 54.8)]
TAPS = [(TAP_OPEN, "open"), (SHIP_TAP, "ship"), *PILLS, (TAP_WAREHOUSE, "warehouse"), (TAP_TABS, "tabs"),
        (TAP_ADD_PHOTO, "photo"), (TAP_AI, "ai"), (TAP_CREATE, "create"),
        (DESK_SHIPMENTS, "d-ship"), (DESK_DASH, "d-dash")]
WHOOSH = [S6, S7, S8, S9]
