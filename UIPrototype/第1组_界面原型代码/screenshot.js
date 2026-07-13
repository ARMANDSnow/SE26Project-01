import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';

const outDir = path.resolve('../迭代1PPT/images');
fs.mkdirSync(outDir, { recursive: true });

const pages = [
  { url: 'http://127.0.0.1:5173/', name: 'dashboard', label: '仪表盘' },
  { url: 'http://127.0.0.1:5173/papers', name: 'papers', label: '论文库' },
  { url: 'http://127.0.0.1:5173/papers/1', name: 'paper-detail', label: '论文详情' },
  { url: 'http://127.0.0.1:5173/qa', name: 'qa', label: '智能问答' },
  { url: 'http://127.0.0.1:5173/graph', name: 'graph', label: '知识图谱' },
  { url: 'http://127.0.0.1:5173/learning', name: 'learning', label: '学习管理' },
];

async function main() {
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1440,900'],
  });

  for (const p of pages) {
    console.log(`Capturing ${p.label} (${p.url})...`);
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });
    
    try {
      await page.goto(p.url, { waitUntil: 'networkidle2', timeout: 15000 });
      // Wait extra time for React rendering
      await new Promise(r => setTimeout(r, 2000));
      const filePath = path.join(outDir, `${p.name}.png`);
      await page.screenshot({ path: filePath, type: 'png', fullPage: false });
      console.log(`  -> ${filePath}`);
    } catch (err) {
      console.error(`  Failed: ${err.message}`);
      // Try with simpler wait
      try {
        await page.goto(p.url, { waitUntil: 'domcontentloaded', timeout: 10000 });
        await new Promise(r => setTimeout(r, 3000));
        const filePath = path.join(outDir, `${p.name}.png`);
        await page.screenshot({ path: filePath, type: 'png', fullPage: false });
        console.log(`  -> ${filePath} (retry success)`);
      } catch (err2) {
        console.error(`  Retry also failed: ${err2.message}`);
      }
    }
    await page.close();
  }

  await browser.close();
  console.log('Done!');
}

main().catch(e => { console.error(e); process.exit(1); });
