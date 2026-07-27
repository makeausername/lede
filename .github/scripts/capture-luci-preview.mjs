import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright-core';

const baseUrl = process.env.PREVIEW_BASE_URL;
const username = process.env.PREVIEW_USERNAME;
const password = process.env.PREVIEW_PASSWORD;
const outputDir = process.env.PREVIEW_OUTPUT_DIR;

if (!baseUrl || !username || !password || !outputDir) {
  throw new Error('Preview environment is incomplete');
}

fs.mkdirSync(outputDir, { recursive: true });

const browser = await chromium.launch({
  executablePath: '/usr/bin/google-chrome',
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});

const context = await browser.newContext({
  locale: 'zh-CN',
  viewport: { width: 1440, height: 1000 },
  ignoreHTTPSErrors: true,
});
const page = await context.newPage();
page.setDefaultTimeout(30_000);

const report = [];

try {
  await page.goto(`${baseUrl}/cgi-bin/luci/`, {
    waitUntil: 'domcontentloaded',
    timeout: 60_000,
  });
  await page.screenshot({
    path: path.join(outputDir, '00-login.png'),
    fullPage: true,
  });

  const userField = page.locator('input[name="luci_username"]');
  const passwordField = page.locator('input[name="luci_password"]');
  if (await userField.count()) {
    await userField.fill(username);
    await passwordField.fill(password);
    await page.locator('input[type="submit"], button[type="submit"]').last().click();
    await page.waitForLoadState('domcontentloaded');
  }

  if (await page.locator('input[name="luci_password"]').count()) {
    throw new Error('LuCI login did not complete');
  }

  const pages = [
    ['01-overview', '/cgi-bin/luci/admin/status/overview'],
    ['02-ssr-client', '/cgi-bin/luci/admin/services/shadowsocksr'],
    ['03-ssr-subscription', '/cgi-bin/luci/admin/services/shadowsocksr/servers'],
    // Runtime-backed UPnP and wireless RPC calls can remain pending under
    // QEMU, so capture them last and never let them block SSR UI evidence.
    ['04-upnp', '/cgi-bin/luci/admin/services/upnp'],
    ['05-wireless', '/cgi-bin/luci/admin/network/wireless'],
  ];

  for (const [name, route] of pages) {
    const capturePage = await context.newPage();
    let response;
    let navigationError = null;
    let screenshotError = null;
    let screenshotMode = 'playwright';

    try {
      response = await capturePage.goto(`${baseUrl}${route}`, {
        waitUntil: 'domcontentloaded',
        timeout: 15_000,
      });
      await capturePage.waitForTimeout(2500);
    } catch (error) {
      navigationError = error instanceof Error ? error.message : String(error);
      await capturePage.waitForTimeout(1000);
    }

    const screenshotPath = path.join(outputDir, `${name}.png`);
    try {
      await capturePage.screenshot({
        path: screenshotPath,
        fullPage: true,
        timeout: 5000,
      });
    } catch (error) {
      screenshotError = error instanceof Error ? error.message : String(error);
      screenshotMode = 'unavailable';
    }
    report.push({
      name,
      route,
      status: response?.status() ?? null,
      title: await capturePage.title(),
      navigationError,
      screenshotMode,
      screenshotError,
    });
    await capturePage.close({ runBeforeUnload: false }).catch(() => {});
  }
} finally {
  fs.writeFileSync(
    path.join(outputDir, 'report.json'),
    `${JSON.stringify(report, null, 2)}\n`,
  );
  await browser.close();
}
