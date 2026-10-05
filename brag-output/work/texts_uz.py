"""Uzbek (Latin) texts of the video. The app interface itself stays in Russian.
Used by render.py when VIDEO_LANG=uz."""

# caption id → inner HTML of the caption block
CAPS = {
    "c2": '<div class="h">Yechim bor.</div><div class="sub">Shaxsiy CRM endi bitta qulay ilovada.</div>',
    "c3a": '<div class="h">Hisob-kitobdagi<br>chalkashlikka chek</div>',
    "c3b": '<div class="h">Hammasi shaffof<br>va tushunarli</div>',
    "c4a": '<div class="h">Yetkazib berish haqida<br>cheksiz savollar?</div>',
    "c4b": '<div class="h">Har bir jo‘natma<br>to‘liq ko‘rinadi</div>',
    "c5a": '<div class="h">Holatni qo‘lda yozib<br>berish shart emas</div>',
    "c5b": '<div class="h">Har bir bosqich<br>nazorat ostida</div>',
    "c6": '<div class="h">Mijoz o‘zinikini ko‘radi.<br>Siz esa hammasini.</div>',
    "c7": '<div class="h">Rasmni yuklang.<br>Qolganini AI to‘ldiradi.</div>',
    "c8a": '<div class="h">Kompyuter uchun<br>to‘liq veb-sayt.</div>',
    "c8b": '<div class="h">Foyda o‘zi<br>hisoblanadi.</div>',
    "c9": '<div class="h">Biznesingizga<br>moslab beramiz.</div>',
}

# exact substrings of stage.html → Uzbek
STAGE = [
    (">14 участников<", ">14 ishtirokchi<"), (">Заказы клиентов<", ">Mijozlar buyurtmalari<"),
    ('<div class="av">З</div>', '<div class="av">M</div>'), ('<div class="av">А</div>', '<div class="av">D</div>'),
    ("<b>Анна</b>Где мой заказ?", "<b>Dilnoza</b>Buyurtmam qayerda?"), ("<b>Анна</b>Отправили?", "<b>Dilnoza</b>Jo‘natdingizmi?"),
    ("<b>Анна</b>Какой у меня баланс?", "<b>Dilnoza</b>Balansimda qancha bor?"),
    ("<b>Вы</b><table", "<b>Siz</b><table"), (">вот таблица, там всё есть<", ">mana jadval, hammasi shu yerda<"),
    ("['Заказ','Модель','Закупка','Цена','Оплата','Остаток']", "['Buyurtma','Model','Xarid','Narx','To‘lov','Qoldiq']"),
    ("Buyer CRM<small>бот</small>", "Buyer CRM<small>bot</small>"),
    ("<b>Buyer CRM</b>Здравствуйте! Здесь ваши заказы, баланс и отправки. Нажмите, чтобы открыть CRM.",
     "<b>Buyer CRM</b>Assalomu alaykum! Buyurtmalar, balans va jo‘natmalar shu yerda. CRMni ochish uchun bosing."),
    ('<div id="inbtn">Открыть CRM</div>', '<div id="inbtn">CRMni ochish</div>'),
    (">Сообщение<", ">Xabar<"), (">Закрыть<", ">Yopish<"), ("<small>мини-приложение</small>", "<small>mini ilova</small>"),
    (">Загрузка…<", ">Yuklanmoqda…<"),
    ("<div>Анна<small>клиент</small></div>", "<div>Dilnoza<small>mijoz</small></div>"),
    ("<b>Анна</b>'+m[1]", "<b>Dilnoza</b>'+m[1]"), ("<b>Вы</b><div class=\"file\">", "<b>Siz</b><div class=\"file\">"),
    ("Отчет_Баланс.xlsx<small>48 КБ · таблица</small>", "Hisobot_Balans.xlsx<small>48 KB · jadval</small>"),
    ("<span>КЛИЕНТ</span>", "<span>MIJOZ</span>"), ("<span>АДМИНИСТРАТОР</span>", "<span>ADMINISTRATOR</span>"),
    ('<div class="chip">Выкуп</div>', '<div class="chip">Xarid</div>'), ('<div class="chip">Доставка</div>', '<div class="chip">Yetkazish</div>'),
    ('<div class="chip">Склад</div>', '<div class="chip">Ombor</div>'), ('<div class="chip">Подписки</div>', '<div class="chip">Obunalar</div>'),
    ('<div class="chip">Свои статусы</div>', '<div class="chip">O‘z statuslaringiz</div>'),
    ("const TXT=['Что с выкупом?','Какой трек?','Посчитай остаток','Где мой заказ?','Отправили уже?','Сколько за доставку?','Я перевёл, проверь','Почему списали?','Скинь фото коробки','Какой курс?','Ответь пж','???','Заказ N7 где?','Когда будет?','Размер 270 есть?','Сколько осталось?'];",
     "const TXT=['Sotib oldingizmi?','Trek raqami qani?','Qoldiqni hisoblang','Buyurtmam qayerda?','Jo‘natdingizmi?','Yetkazish qancha?','Pul o‘tkazdim, tekshiring','Nega yechildi?','Quti rasmini tashlang','Kurs qancha?','Javob bering iltimos','???','N7 buyurtma qani?','Qachon keladi?','270 o‘lcham bormi?','Qancha qoldi?'];"),
    ("const NM=['Анна','Игорь','Дмитрий','Алия','Тимур','Ольга','Руслан','Мария','Саша'];",
     "const NM=['Dilnoza','Aziz','Jasur','Malika','Bekzod','Nodira','Sardor','Shahzoda','Otabek'];"),
    # Uzbek words are longer: slightly smaller headline type
    (".cap .h{font-size:78px;", ".cap .h{font-size:70px;"),
]

# pain-chat messages (scenes 3-5)
PAIN = {
    "Какой у меня баланс?": "Balansimda qancha qoldi?", "Сколько за что сняли?": "Nimaga qancha yechildi?",
    "Вы уже отправили?": "Jo‘natdingizmi?", "Когда?": "Qachon?", "Какой трек?": "Trek raqami qani?",
    "Можно фото коробки?": "Quti rasmini tashlaysizmi?",
    "Мои заказы выкупили?": "Buyurtmalarim sotib olindimi?", "Он уже приехал к вам?": "Omborga keldimi?",
    "В карго передали?": "Kargoga topshirdingizmi?",
}

# callouts under the phones / laptop
CALLOUTS = {
    "Клиент видит только цену": "Mijoz faqat narxni ko‘radi", "Ваша маржа на каждом заказе": "Har bir buyurtmadagi foydangiz",
    "Управление заказом": "Buyurtmani boshqarish", "Клиент видит сразу": "Mijoz darhol ko‘radi",
    "Клиент видит цену": "Mijoz narxni ko‘radi", "Закупка видна только вам": "Xarid narxi faqat sizga",
    "Прибыль по каждому заказу": "Har bir buyurtma foydasi", "Без Excel и калькулятора": "Excel va kalkulyatorsiz",
}
