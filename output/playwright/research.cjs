const { chromium } = require('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1030-493-0_26.1030.493.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/playwright');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Users/Lukesu/AppData/Local/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe' });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    for (const [name, url] of [
      ['mercury-reference', 'https://demo.mercury.com/dashboard'],
      ['warm-reference', 'https://cdn.dribbble.com/userupload/45788397/file/3b2203c17835714467b693bf7232840d.png?resize=1440x&vertical=center'],
      ['copilot-reference', 'https://www.copilot.money/img/home/hero/screen-clean.webp'],
    ]) {
      try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 25000 });
        await page.waitForTimeout(1800);
        await page.screenshot({ path: path.join(__dirname, name + '.png') });
        console.log(name, page.url(), await page.title());
      } catch(e) { console.log(name, e.message.slice(0, 140)); }
    }
  } finally { await browser.close(); }
})();
