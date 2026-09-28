# Исходное ТЗ владельца (27.09.2026)

> Сохранено как есть, для контекста. Часть решений с тех пор изменена по просьбе владельца —
> актуальное состояние в [CLAUDE.md](../CLAUDE.md) (§9 «Ключевые решения») и
> [architecture.md](architecture.md). Главные отличия:
>
> * база — **SQLite на своём сервере** (Firestore/Firebase Storage — только опционально);
> * номера заказов — **N1, N2, …** (заглавная N, с единицы), а не `n1…n125`; старые данные не переносились;
> * фото — WebP **до ~500 КБ** (не 80–120 КБ), квадрат 1:1 на белом фоне;
> * бот **ничего не пишет в группу**, вопросы — админу в личку; заказы принимаются от любого участника
>   группы (клиент и его помощники), Mini App — только клиенту;
> * стоимость доставки списывается с баланса; есть перезаказ; после отправки возвратов нет;
> * фаза 9 (AI-ассистент, голос) ещё не начата.
>
> Фраза в начале ТЗ про «уже есть бот и API» не подтвердилась: проект начат с нуля.

---

ROLE
Ты — Senior Full-Stack Engineer / Software Architect с сильной экспертизой в:

* Python 3
* aiogram 3.x
* Firebase Firestore
* Firebase Storage
* Firebase Hosting
* Firebase Security Rules
* React + TypeScript
* Telegram Bot API
* Telegram Mini Apps
* Google Gemini API
* REST API
* системах учета заказов и финансов
* безопасной архитектуре CRM

Из того, что сейчас было сделано, это был создан бот. Уже есть бот и API, надо поправить кей. И уже настроен типа Firebase. Все данные уже везде перечислены.
1. ГЛАВНАЯ ЗАДАЧА
Необходимо разработать и постепенно расширять собственную CRM-систему для байера — посредника по покупке товаров в Южной Корее.
В системе участвуют только:

1. ADMIN / BUYER — владелец CRM.
2. CLIENT — один постоянный B2B-клиент.

Архитектуру не нужно искусственно усложнять под SaaS или множество клиентов.
При этом код должен быть структурирован так, чтобы в будущем расширение было возможно без полного переписывания системы.
Основная валюта системы:
KRW — Korean Won.
Дополнительно баланс должен отображаться в USD по установленному администратором курсу.
2. ОБЩАЯ ЭКОСИСТЕМА
CRM состоит из четырех основных частей:
A. Telegram Group Bot
Бот находится в Telegram-группе, где клиент отправляет заказы.
Бот должен:

* получать сообщения с заказами;
* обрабатывать фотографии;
* сохранять товары;
* определять размер;
* сохранять ссылки;
* создавать заказы;
* отслеживать статусы;
* выполнять административные команды.

B. Telegram Admin Bot / AI Assistant
У ADMIN есть личный чат с ботом.
Через него ADMIN может:

* добавлять заказ;
* менять статус;
* менять цену;
* добавлять комментарий;
* создавать отправку;
* смотреть финансовую информацию;
* запрашивать аналитику;
* управлять заказами обычным текстом;
* использовать Gemini как AI-ассистента.

AI никогда не должен иметь неограниченный прямой доступ к Firestore.
C. Telegram Mini App
В Mini App существуют два режима.
CLIENT MODE
Клиент может только:

* смотреть заказы;
* смотреть статусы;
* смотреть фотографии;
* смотреть комментарии, доступные клиенту;
* смотреть историю;
* смотреть отправки;
* смотреть баланс;
* смотреть баланс в KRW и USD.

CLIENT является полностью read-only пользователем.
Он не может:

* менять статус;
* менять цену;
* менять баланс;
* добавлять заказ;
* удалять заказ;
* редактировать отправки.

ADMIN MODE
ADMIN может:

* создавать заказ;
* редактировать заказ;
* менять статус;
* менять цены;
* менять курс KRW/USD;
* добавлять комментарии;
* выбирать несколько заказов;
* массово менять статус;
* создавать отправки;
* прикреплять фото отправки;
* указывать вес;
* указывать box number;
* указывать стоимость доставки;
* управлять финансами.

D. Desktop Web Dashboard
Необходимо создать полноценную responsive web-панель администратора.
Она должна использовать ту же backend-логику и ту же базу данных, что и Mini App.
Dashboard должен быть удобен для работы с компьютера.
Не нужно создавать отдельную независимую бизнес-логику для сайта и Telegram Mini App.
Использовать общие API/service modules.
3. ТЕКУЩИЙ TECH STACK
Database
Firebase Firestore.
File Storage
Firebase Storage.
Telegram Backend
Python 3.
aiogram 3.x.
firebase-admin.
Web
Предпочтительно:
React
TypeScript
Vite
Firebase Hosting.
AI
Google Gemini API.
4. ВАЖНО: СНАЧАЛА ИЗУЧИ СУЩЕСТВУЮЩИЙ ПРОЕКТ
Перед любыми крупными изменениями:

1. Изучи структуру репозитория.
2. Найди существующий Telegram bot.
3. Найди Firebase configuration.
4. Найди существующие handlers.
5. Найди Firestore service layer.
6. Найди существующие модели.
7. Найди реализованные команды.
8. Определи, что уже работает.
9. Не переписывай рабочий функционал без необходимости.
10. Предложи минимальный безопасный набор изменений.

Если структура проекта слабая, постепенно проведи refactoring.
Не устраивай полный rewrite без необходимости.
5. СУЩЕСТВУЮЩАЯ FIRESTORE СТРУКТУРА
client_info/main_client
Поля:

```
telegram_id: number
name: string
balance: number
```

balance хранится в KRW.
Баланс может быть:

* положительным;
* равным нулю;
* отрицательным.

Отрицательный баланс означает долг клиента и является допустимым состоянием.
6. ORDERS
Существующая коллекция:

```
orders
```

ID документов:

```
n1
n2
n3
...
n125
```

Поля:

```
order_id
status
purchase_price
client_price
profit
cargo_code
```

profit:

```
client_price - purchase_price
```

7. РАСШИРИТЬ МОДЕЛЬ ORDER
Рекомендуемая структура:

```
order_id: string

status:
new
bought
warehouse
cargo
delivered
cancelled

brand: string | null
model: string | null

size: string | null

purchase_price: number
client_price: number
profit: number

cargo_code: string | null

photo_url: string | null
thumbnail_url: string | null

source_url: string | null

source_chat_id: number | null
source_message_id: number | null

shipment_id: string | null

client_comment: string | null
internal_comment: string | null

attention_required: boolean

created_at
updated_at
bought_at
warehouse_at
cargo_at
delivered_at
cancelled_at

created_by
updated_by
```

Не обязательно создавать все поля сразу.
Добавляй их постепенно по мере реализации функционала.
8. ОБРАБОТКА ЗАКАЗА ИЗ TELEGRAM GROUP
Типичный заказ клиента может содержать:

* фотографию товара;
* размер;
* текст;
* ссылку;
* несколько сообщений подряд.

Необходимо разработать механизм получения заказа.
9. ОБРАБОТКА ФОТО
Когда бот получает фотографию товара:

1. скачать оригинал;
2. привести изображение к стандартному размеру;
3. сохранить пропорции;
4. не растягивать изображение;
5. сжать;
6. преобразовать в WebP;
7. целевой размер файла примерно 80–120 KB;
8. качество изображения должно оставаться достаточным для визуального определения товара;
9. сохранить файл в Firebase Storage;
10. получить URL;
11. сохранить URL в заказ.

Все карточки в CRM должны использовать стандартизированные изображения.
Создать также thumbnail, если это улучшит производительность интерфейса.
Не хранить binary image внутри Firestore.
10. GEMINI IMAGE PARSER
Gemini используется для анализа изображения.
Его задача:
определить, если возможно:

```
{
  "brand": "",
  "model": "",
  "category": "",
  "color": "",
  "confidence": 0
}
```

Gemini НЕ должен самостоятельно принимать финансовые решения.
Gemini НЕ должен придумывать данные при низкой уверенности.
Если информация неизвестна:

```
null
```

или пустое значение.
Не галлюцинировать бренд или модель.
11. СОЗДАНИЕ DRAFT ORDER
После получения нового заказа из Telegram:
создать заказ со статусом:

```
new
```

и сохранить:

* photo;
* size;
* source URL;
* original Telegram message reference;
* Gemini parsing result;
* timestamp.

12. СТАТУСЫ
Основные статусы:

```
new
bought
warehouse
cargo
delivered
cancelled
```

UI должен отображать их человекопонятно.
Например:

```
NEW → Новый заказ
BOUGHT → Выкуплен
WAREHOUSE → На складе
CARGO → Отправлен
DELIVERED → Доставлен
CANCELLED → Отменен
```

В интерфейсе использовать visual stepper.
Например:

```
● → ● → ● → ●
Заказ → Выкуплен → Склад → Карго → Доставлен
```

Каждый этап может иметь отдельную иконку.
13. СУЩЕСТВУЮЩАЯ КОМАНДА /buy
Пример:

```
/buy 5 140000 170000
```

означает:

```
order = n5
purchase_price = 140000
client_price = 170000
profit = 30000
```

После покупки:

```
status = bought
```

Из balance клиента вычитается:

```
170000 KRW
```

14. КРИТИЧЕСКАЯ ФИНАНСОВАЯ ЗАЩИТА
Нельзя допускать повторного списания денег при повторном вызове `/buy`.
Например:

```
/buy 5 ...
```

выполненный дважды НЕ должен дважды уменьшить balance.
Использовать:

* Firestore transaction;
* проверку предыдущего состояния заказа;
* idempotency logic.

Финансовые операции должны быть атомарными.
15. /cancel
При отмене:

```
status = cancelled
```

Если ранее client_price был списан с balance, он должен быть возвращен.
Но возврат также должен быть idempotent.
Нельзя дважды вернуть деньги при повторном `/cancel`.
16. НОВАЯ КОМАНДА /cargo
Формат:

```
/cargo TRACKCODE 5 10 18 23
```

или:

```
/cargo TRACKCODE n5 n10 n18
```

Бот должен автоматически нормализовать ID.
Например:

```
5 → n5
```

Для каждого заказа:

```
cargo_code = TRACKCODE
status = cargo
```

Обновление нескольких заказов выполнять через batch write.
Вернуть ADMIN результат:

```
✅ Обновлено: n5, n10, n18
⚠️ Не найдено: n23
```

17. ВАЖНАЯ НОВАЯ СУЩНОСТЬ — SHIPMENTS
Cargo code внутри order недостаточно.
Нужно создать отдельную коллекцию:

```
shipments
```

Shipment — это одна физическая отправка группы товаров клиенту.
Пример:

```
shipment_id: SHP-2026-001

shipment_number: 1

shipment_date

box_number

tracking_code

weight_kg

shipping_cost_krw

photo_url

order_ids: [
  "n5",
  "n7",
  "n12"
]

comment

created_at

created_by
```

18. СОЗДАНИЕ ОТПРАВКИ В ADMIN MINI APP
ADMIN открывает список заказов.
Напротив каждого заказа есть checkbox.
ADMIN выбирает:

```
☑ n5
☑ n7
☑ n12
```

Нажимает:

```
Создать отправку
```

Открывается modal.
Поля:

```
Box Number
Tracking Number
Weight
Shipping Cost
Shipment Date
Comment
Photo
```

После подтверждения:

1. создается Shipment;
2. order_ids сохраняются в Shipment;
3. каждому заказу присваивается shipment_id;
4. status заказов становится cargo;
5. при необходимости записывается cargo_code.

Выполнить операцию безопасно и атомарно.
19. CLIENT: ВКЛАДКА «ОТПРАВКИ»
Клиент видит список отправок.
Например:

```
Отправка #18
12 сентября 2026
8 товаров
12.5 кг
```

При нажатии:
показывается:

* фотография отправки;
* tracking number;
* box number;
* дата;
* вес;
* список товаров;
* фотографии товаров;
* комментарий.

20. БАЛАНС
На главном экране клиента сверху показывать:

```
Balance

₩ 12,500,000
$ 9,250
```

Если balance отрицательный:

```
- ₩ 2,400,000
- $ 1,780
```

Отрицательный баланс не является ошибкой.
Он должен быть визуально заметным.
21. EXCHANGE RATE
ADMIN может вручную задавать курс.
Использовать понятное поле:

```
krw_per_usd
```

Например:

```
krw_per_usd = 1350
```

Тогда:

```
USD = KRW / 1350
```

Курс хранить централизованно, например:

```
settings/general
```


```
krw_per_usd
updated_at
updated_by
```

CLIENT не может менять курс.
22. КРИТИЧЕСКИ ВАЖНО: BALANCE LEDGER
Нельзя использовать только поле:

```
client_info.balance
```

Необходимо добавить финансовую историю.
Коллекция:

```
transactions
```

Каждое изменение balance создает transaction.
Пример:

```
transaction_id

type:
order_charge
order_refund
deposit
adjustment
shipping_charge

amount_krw

balance_before
balance_after

order_id
shipment_id

comment

created_at
created_by
```

Пример покупки:

```
type = order_charge
amount_krw = -170000
```

Пополнение:

```
type = deposit
amount_krw = +5000000
```

Refund:

```
type = order_refund
amount_krw = +170000
```

Таким образом всегда можно восстановить историю баланса.
23. CLIENT: ИСТОРИЯ БАЛАНСА
Если клиент нажимает на Balance:
открывается страница:

```
История баланса
```

Минималистичный список:

```
27 Sep
n125
Nike Air Max
- ₩170,000

26 Sep
Пополнение
+ ₩5,000,000
```

Дополнительно можно показывать маленькую thumbnail товара.
24. КОММЕНТАРИИ
Для заказов необходимо поддерживать два типа комментариев.
client_comment
Виден клиенту.
Например:

```
Поставка задерживается на 2 дня.
```

internal_comment
Виден только ADMIN.
Например:

```
Продавец пока не отвечает.
```

Никогда не показывать internal_comment клиенту.
25. ATTENTION / IMPORTANT
Для заказа добавить:

```
attention_required = true/false
```

ADMIN может отметить заказ как требующий внимания.
CLIENT UI должен визуально выделять такой заказ.
Например:

```
⚠ Требуется внимание
```

26. TELEGRAM NOTIFICATIONS
Для важных событий можно отправлять клиенту Telegram-уведомление.
Например:

```
📦 Заказ n125 отправлен.

Tracking:
123456789

Открыть заказ →
```

Или:

```
⚠️ Обновление по заказу n125

Поставка задерживается на 2 дня.
```

Не отправлять уведомление на каждое техническое изменение.
Создать понятную notification policy.
27. CLIENT MINI APP — HOME
Главный экран должен быть визуально простым.
Верх:

```
Balance
₩ ...
$ ...
```

Затем summary:

```
New
Bought
Warehouse
Cargo
Delivered
```

Ниже:

```
Orders
```

Каждый order отображается карточкой.
28. ORDER CARD
Карточка:

```
[PHOTO]

Nike
Air Max 95
Size 270

₩ 170,000

● ● ● ○
Warehouse
```

Не перегружать карточку информацией.
29. ORDER DETAILS
При нажатии открывать detail page или modal.
Показывать:

* большое изображение;
* order ID;
* brand;
* model;
* size;
* client price;
* status;
* status timeline;
* tracking;
* shipment;
* client comment;
* timestamps.

30. CLIENT MINI APP TABS
Минимально:

```
Home
Orders
Shipments
Balance
```

Можно добавить:

```
Notifications
```

только если это действительно необходимо.
Не перегружать navigation.
31. ADMIN MINI APP
Admin UI может быть функциональнее.
Основные разделы:

```
Dashboard
Orders
Shipments
Finance
Settings
```

32. ADMIN ORDER TABLE
Для ADMIN desktop mode предпочтительно использовать таблицу.
Колонки:

```
checkbox
photo
order_id
brand/model
size
status
purchase price
client price
profit
shipment
date
actions
```

Поддержать:

* search;
* filters;
* sort;
* pagination / lazy loading.

33. MASS ACTIONS
После выбора нескольких orders:
появляется action toolbar:

```
Change Status
Create Shipment
Add Comment
Mark Attention
```

Не делать bulk delete как обычное действие.
34. MANUAL ORDER CREATION
ADMIN должен иметь форму:

```
Photo
Brand
Model
Size
Link
Purchase Price
Client Price
Comment
Status
```

Order ID формируется автоматически.
Не заставлять пользователя самостоятельно вычислять следующий номер.
35. ORDER ID GENERATION
Не использовать небезопасную схему:

```
прочитать последний ID + 1
```

без transaction.
При параллельных операциях это может создать duplicate ID.
Создать counter, например:

```
counters/orders
next_id
```

и увеличивать его через Firestore transaction.
Результат:

```
n126
```

36. AUTHORIZATION
Есть две роли:

```
admin
client
```

Telegram ID ADMIN хранить безопасно через environment variable или защищенную конфигурацию.
Telegram ID клиента уже хранится в:

```
client_info/main_client.telegram_id
```

37. TELEGRAM MINI APP SECURITY
НЕ полагаться только на:

```
Telegram.WebApp.initDataUnsafe.user.id
```

Это можно использовать для UI.
Но сервер должен проверять:

```
Telegram.WebApp.initData
```

с использованием Telegram Bot Token и официального алгоритма проверки подписи.
Только после успешной server-side validation определить:

```
admin
или
client
```

CLIENT API endpoints должны быть read-only.
38. FIREBASE SECURITY
Не разрешать frontend напрямую изменять чувствительные финансовые данные.
Критические операции выполнять через backend:

* изменение balance;
* `/buy`;
* `/cancel`;
* adjustment;
* shipment creation;
* price changes;
* bulk updates.

Настроить Security Rules.
39. AUDIT LOG
Создать:

```
audit_logs
```

Записывать важные изменения.
Например:

```
actor
action
entity_type
entity_id

before
after

timestamp
source
```

source:

```
telegram_bot
mini_app
web_dashboard
ai_assistant
```

40. AI ASSISTANT — ГЛАВНОЕ ПРАВИЛО БЕЗОПАСНОСТИ
Gemini НЕ получает возможность свободно выполнять Firestore commands.
Использовать следующую архитектуру:

```
USER
↓
Gemini
↓
Structured Intent
↓
Validator
↓
Allowed Action
↓
Application Service
↓
Firestore
```

Gemini только интерпретирует текст.
41. ALLOWED AI ACTIONS
Создать whitelist.
Например:

```
get_order
list_orders
create_order
update_order_status
update_order_comment
update_order_price
create_shipment
get_balance
get_finance_summary
get_profit_summary
search_orders
```

AI не может выполнить неизвестный action.
42. STRUCTURED AI OUTPUT
Gemini должен возвращать структурированный объект.
Пример:

```
{
  "intent": "update_order_status",
  "order_ids": ["n5", "n7"],
  "new_status": "warehouse",
  "confidence": 0.98
}
```

Backend проверяет:

```
intent ∈ ALLOWED_INTENTS
```

затем отдельно валидирует каждый parameter.
43. CONFIRMATION RULE
READ actions выполняются сразу.
Например:

```
Покажи прибыль за сентябрь.
```

WRITE actions могут потребовать confirmation.
Особенно:

* изменение balance;
* изменение цены;
* cancel;
* массовое изменение;
* создание financial adjustment;
* удаление;
* возврат денег.

Пример:
Пользователь:

```
Отмени n125
```

AI отвечает:

```
Вы хотите отменить заказ n125.

К возврату на баланс:
₩170,000

Текущий баланс:
₩2,300,000

После операции:
₩2,470,000

[Подтвердить]
[Отмена]
```

Только после confirmation выполнить действие.
44. AI NEVER DOES
AI никогда самостоятельно не должен:

* удалять коллекции;
* массово удалять документы;
* менять Telegram IDs;
* менять Security Rules;
* изменять Firebase credentials;
* выполнять произвольный Firestore query из пользовательского текста;
* выполнять произвольный код;
* менять balance без контролируемой финансовой операции;
* изменять financial history;
* удалять audit logs.

45. VOICE COMMANDS
В будущем ADMIN может отправлять voice message.
Pipeline:

```
Voice
↓
Speech-to-text
↓
Gemini intent parser
↓
Validator
↓
Confirmation if necessary
↓
CRM action
```

Использовать тот же allowed-actions layer.
Не создавать отдельную незащищенную логику для voice.
46. AI ANALYTICS
ADMIN может спрашивать:

```
Какая прибыль за сентябрь?
```


```
Сколько товаров сейчас на складе?
```


```
Какие заказы больше 7 дней находятся на warehouse?
```


```
Посчитай прибыль по этим заказам.
```


```
Сколько денег сейчас клиент должен?
```

AI может анализировать данные CRM.
Но расчеты по возможности делать программно.
Gemini должен объяснять результат, а не самостоятельно вычислять важные финансовые значения из непроверенного текста.
47. DESIGN
Визуальный стиль:

* modern;
* minimalist;
* premium;
* calm;
* clean;
* мягкие нейтральные цвета;
* немного masculine;
* много whitespace;
* аккуратные карточки;
* rounded corners;
* subtle shadows;
* современная typography.

Избегать:

* чрезмерно ярких цветов;
* «детского» дизайна;
* большого количества gradients;
* перегруженности;
* огромных icons;
* слишком большого количества информации на одной карточке.

48. RESPONSIVE
Интерфейс должен хорошо работать на:

```
Telegram mobile Mini App
Phone browser
Tablet
Desktop
```

Mobile и desktop могут иметь разное представление.
Например:

```
mobile → cards
desktop → table
```

49. DATA ARCHITECTURE
Целевая структура Firestore приблизительно:

```
client_info/
    main_client

orders/
    n1
    n2
    n3

shipments/
    SHP-...

transactions/
    ...

settings/
    general

audit_logs/
    ...

counters/
    orders
    shipments
```

Не мигрировать существующие данные без необходимости.
50. SERVICE LAYER
Не писать Firestore operations хаотично внутри Telegram handlers.
Использовать отдельные modules:

```
services/
    order_service.py
    finance_service.py
    shipment_service.py
    image_service.py
    ai_service.py
    notification_service.py
```

Telegram handlers должны быть thin.
Пример:

```
handler
↓
OrderService
↓
FirestoreRepository
```

51. ERROR HANDLING
Любая операция должна выдавать понятную ошибку.
Не показывать пользователю raw stack trace.
Логи должны сохранять техническую информацию.
Например:

```
❌ Заказ n125 не найден.
```

вместо Firebase exception.
52. FIRESTORE OPERATIONS
Использовать:

* transaction — когда связаны деньги и order state;
* batch write — для нескольких связанных документов без сложной conditional logic.

Особенно:

```
buy
cancel
balance adjustments
shipment creation
```

53. TIME
Все timestamps хранить в UTC / Firestore Timestamp.
В UI отображать в:

```
Asia/Seoul
```

54. ROADMAP
Не пытайся реализовать всю CRM одновременно.
Работай этапами.
PHASE 1 — FOUNDATION

* изучить существующий код;
* привести структуру проекта в порядок;
* создать service layer;
* создать repositories;
* проверить Firebase initialization;
* environment variables;
* config;
* error handling.

PHASE 2 — ORDER BACKEND

* `/buy`;
* `/cancel`;
* `/status`;
* `/cargo`;
* idempotency;
* Firestore transactions;
* order counter.

PHASE 3 — IMAGE PIPELINE

* Telegram image;
* resize;
* WebP;
* 80–120 KB;
* Firebase Storage;
* Gemini parser;
* draft order.

PHASE 4 — FINANCE

* transaction ledger;
* balance;
* deposits;
* refunds;
* adjustments;
* exchange rate.

PHASE 5 — SHIPMENTS

* shipment collection;
* bulk order selection;
* shipment creation;
* photo;
* weight;
* box;
* cost;
* tracking.

PHASE 6 — CLIENT MINI APP

* Telegram auth;
* home;
* orders;
* order details;
* shipments;
* balance history.

PHASE 7 — ADMIN MINI APP

* dashboard;
* orders;
* bulk actions;
* shipment creation;
* finance;
* settings.

PHASE 8 — DESKTOP WEB DASHBOARD
Reuse ADMIN frontend where possible.
PHASE 9 — AI ASSISTANT

* intent schema;
* whitelist;
* validators;
* confirmation;
* analytics;
* voice support.

PHASE 10 — HARDENING

* Security Rules;
* audit log;
* logging;
* tests;
* backup strategy;
* performance improvements.

55. DEVELOPMENT RULES
Перед реализацией каждого большого feature:

1. Кратко объясни текущую архитектуру.
2. Скажи, какие существующие файлы затронешь.
3. Не создавай duplicate logic.
4. Сделай implementation.
5. Проверь edge cases.
6. Добавь или обнови tests.
7. Покажи, что изменилось.
8. Если нужна Firebase migration — объясни отдельно.
9. Не удаляй рабочий код без причины.

56. НЕ ПРИДУМЫВАЙ БИЗНЕС-ЛОГИКУ МОЛЧА
Если есть небольшая техническая неопределенность:
прими разумное безопасное решение самостоятельно и укажи его.
Если решение может:

* изменить финансовую логику;
* потерять данные;
* изменить смысл balance;
* изменить расчет profit;
* повлиять на безопасность;

тогда сначала явно обозначь вопрос.
Но не задавай ненужные вопросы по мелочам, если можешь выбрать стандартное безопасное решение.
57. DEFINITION OF DONE
Feature считается готовым только если:

* работает основной сценарий;
* обработаны ошибки;
* есть role validation;
* нет очевидного способа двойного финансового списания;
* Firestore data consistency сохранена;
* UI показывает loading/error/empty states;
* операция логируется там, где это необходимо;
* существующий функционал не сломан.

58. ТЕКУЩАЯ ЗАДАЧА ДЛЯ ТЕБЯ
После прочтения этого документа:

1. Проанализируй существующий repository.
2. Сопоставь существующий код с этой архитектурой.
3. Не начинай переписывать все сразу.
4. Покажи:


```
A. Что уже реализовано
B. Что реализовано частично
C. Чего нет
D. Какие архитектурные проблемы уже существуют
E. Что нужно изменить прежде всего
```

После этого предложи следующий конкретный development step.
Если текущий проект позволяет, первым практическим этапом считаем:

```
/cargo + shipment architecture + подготовка service layer
```

Но если перед этим есть критическая проблема в существующей архитектуре, сначала исправь ее.
