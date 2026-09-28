# Исходник инструкции `docs/guide.pdf`

* `guide.html` — весь текст инструкции (A4, каждая страница — `<section class="page">`).
* `img/` — скриншоты Mini App (сняты в демо-режиме `python -m crm.server --demo` через Playwright,
  телефон 390×844, масштаб 2×) и пример фото заказа.
* `render.mjs` — собирает PDF: `npm i --no-save playwright && npx playwright install chromium && node render.mjs`.

После правок проверьте, что ни одна страница не переполнилась (число страниц и оглавление на стр. 1),
и что номера страниц в оглавлении совпадают.
