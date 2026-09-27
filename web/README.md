# Mini App и веб-панель

React + TypeScript + Vite. Одно приложение: после проверки Telegram-подписи сервер
возвращает роль, и открывается интерфейс клиента (только просмотр) или администратора.
На телефоне — карточки и нижние вкладки, на компьютере — боковое меню и таблица заказов.

```bash
npm install
npm run dev        # http://localhost:5173, API проксируется на localhost:8080
npm run build      # сборка в dist/, её раздаёт `python -m crm.server`
npm run typecheck && npm test
```

Для локального просмотра без Telegram запустите бэкенд в демо-режиме
(`python -m crm.server --demo` в папке backend) — на странице появится выбор роли.
