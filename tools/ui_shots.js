const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const file = "file://" + path.resolve(process.argv[2]);
const out = process.argv[3];
fs.mkdirSync(out, { recursive: true });
const report = [];
(async () => {
try {
  const browser = await chromium.launch({ channel: 'chrome', args: ['--no-sandbox'] });
  async function overflow(page, label) {
    const r = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth, h: document.documentElement.scrollHeight }));
    report.push(`${label}: scrollWidth=${r.sw} innerWidth=${r.iw} pageHeight=${r.h} horizontalOverflow=${r.sw > r.iw + 1}`);
  }
  // desktop
  let page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(file);
  await page.waitForSelector("#list .card");
  await page.screenshot({ path: `${out}/desktop-1-open.png` });
  await overflow(page, "desktop-open");
  const boxes = await page.$$("#list input[type=checkbox]");
  await boxes[0].check({ timeout: 5000 }); await boxes[1].check({ timeout: 5000 }); await boxes[2].check({ timeout: 5000 });
  await page.click("#cmpbtn");
  await page.screenshot({ path: `${out}/desktop-2-compare.png` });
  await page.fill("#q", "as");
  await page.selectOption("#f", "attention");
  await page.screenshot({ path: `${out}/desktop-3-filtered.png` });
  await overflow(page, "desktop-filtered");
  await page.close();
  // laptop 1280
  page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  await page.goto(file); await page.waitForSelector("#list .card");
  await page.screenshot({ path: `${out}/laptop-1280.png` });
  await page.close();
  // mobile
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(file); await page.waitForSelector("#list .card");
  await page.screenshot({ path: `${out}/mobile-1-list.png` });
  await overflow(page, "mobile-list");
  const opens = await page.$$("#list .openbtn");
  await opens[1].click({ timeout: 5000 });
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${out}/mobile-2-detail.png` });
  await overflow(page, "mobile-detail");
  await page.screenshot({ path: `${out}/mobile-3-detail-full.png`, fullPage: true });
  const tap = await page.evaluate(() => Array.from(document.querySelectorAll("button,input,select")).filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && (r.height < 40); }).map(e => e.tagName + ":" + (e.getAttribute("aria-label") || e.id || e.textContent).slice(0, 30)).slice(0, 12));
  report.push("small tap targets (<40px high): " + JSON.stringify(tap));
  report.push("page errors: " + JSON.stringify(errors));
  fs.writeFileSync(`${out}/report.txt`, report.join("\n") + "\n");
  await browser.close();
} catch (e) { report.push('SCRIPT ERROR: ' + (e && e.stack || e)); fs.writeFileSync(`${out}/report.txt`, report.join('\n') + '\n'); }
})();
