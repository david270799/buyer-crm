// Renders docs/guide/guide.html into docs/guide.pdf (A4, page numbers in the footer).
//   cd docs/guide && npm i --no-save playwright && npx playwright install chromium
//   node render.mjs            # writes ../guide.pdf
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const dir = path.dirname(fileURLToPath(import.meta.url));
const out = process.argv[2] ?? path.join(dir, "..", "guide.pdf");
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto(`file://${dir}/guide.html`);
await page.waitForLoadState("networkidle");
await page.pdf({
  path: out,
  format: "A4",
  printBackground: true,
  preferCSSPageSize: true,
  displayHeaderFooter: true,
  headerTemplate: "<span></span>",
  footerTemplate:
    '<div style="width:100%;font-size:8px;color:#8a8d94;font-family:Liberation Sans,Arial;text-align:center;">' +
    'Buyer CRM · установка и проверка · <span class="pageNumber"></span> / <span class="totalPages"></span></div>',
});
await browser.close();
console.log(`written ${out}`);
