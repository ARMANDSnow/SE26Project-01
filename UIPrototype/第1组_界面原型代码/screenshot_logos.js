const puppeteer = require('puppeteer');
const path = require('path');

(async () => {
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1200, height: 1000, deviceScaleFactor: 2 });

  const htmlPath = path.join(__dirname, 'logo_preview.html');
  await page.goto('file://' + htmlPath, { waitUntil: 'networkidle0' });
  await new Promise(r => setTimeout(r, 500));

  // 整体预览图
  await page.screenshot({
    path: path.join(__dirname, 'images', 'logos_overview.png'),
    fullPage: true
  });
  console.log('Saved: logos_overview.png');

  // 分别截取每个 logo
  const cards = await page.$$('.card');
  const names = ['A', 'B', 'C', 'D'];
  for (let i = 0; i < cards.length; i++) {
    const card = cards[i];
    const logoWrap = await card.$('.logo-wrap');
    if (logoWrap) {
      await logoWrap.screenshot({
        path: path.join(__dirname, 'images', `logo_${names[i]}.png`)
      });
      console.log(`Saved: logo_${names[i]}.png`);
    }
  }

  await browser.close();
})();
