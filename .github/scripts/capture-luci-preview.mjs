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
    ['02-wireless', '/cgi-bin/luci/admin/network/wireless'],
    ['03-upnp', '/cgi-bin/luci/admin/services/upnp'],
    ['04-ssr-client', '/cgi-bin/luci/admin/services/shadowsocksr'],
    ['05-ssr-subscription', '/cgi-bin/luci/admin/services/shadowsocksr/servers'],
  ];

  for (const [name, route] of pages) {
    const response = await page.goto(`${baseUrl}${route}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60_000,
    });
    await page.waitForTimeout(2500);
    await page.screenshot({
      path: path.join(outputDir, `${name}.png`),
      fullPage: true,
    });
    report.push({
      name,
      route,
      status: response?.status() ?? null,
      title: await page.title(),
    });
  }
} finally {
  fs.writeFileSync(
    path.join(outputDir, 'report.json'),
    `${JSON.stringify(report, null, 2)}\n`,
  );
  await browser.close();
}
