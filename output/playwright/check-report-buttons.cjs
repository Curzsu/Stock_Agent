const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1030-493-0_26.1030.493.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/playwright');
(async () => {
  const html = fs.readFileSync('frontend/index.html', 'utf8');
  const css = fs.readFileSync('frontend/workbench.css', 'utf8');
  const base = html.match(/<style>([\s\S]*?)<\/style>/)[1];
  const buttons = html.match(/<div class="report-actions">([\s\S]*?)<\/div>/)[1];
  const browser = await chromium.launch({headless: true, executablePath: 'C:/Users/Lukesu/AppData/Local/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe'});
  try {
    const page = await browser.newPage();
    await page.setContent(`<style>${base}\n${css}</style><div class="workbench-report"><div class="report-actions">${buttons}</div></div>`);
    for (const selector of ['.report-btn-primary', '.report-btn-pdf']) {
      const button = page.locator(selector);
      const read = () => button.evaluate(el => ({color: getComputedStyle(el).color, background: getComputedStyle(el).backgroundImage, backgroundColor: getComputedStyle(el).backgroundColor}));
      const normal = await read();
      assert(normal.background !== 'none' || normal.backgroundColor !== 'rgba(0, 0, 0, 0)', `${selector} background is visible`);
      if (selector.includes('pdf')) await button.evaluate(el => { el.disabled = false; el.classList.remove('loading'); });
      await button.hover();
      const hover = await read();
      assert(hover.background !== 'none' || hover.backgroundColor !== 'rgba(0, 0, 0, 0)', `${selector} hover background is visible`);
      console.log(selector, JSON.stringify({normal, hover}));
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
