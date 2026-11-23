// Renders assets/*.png with Playwright from reports/dashboard.html, docs/example-slack-payload.json and docs/benchmark.json.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const bench = JSON.parse(fs.readFileSync(path.join(root, 'docs/benchmark.json')));
const payload = JSON.parse(fs.readFileSync(path.join(root, 'docs/example-slack-payload.json')));

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
const mrkdwn = (s) => esc(s).replace(/\*([^*]+)\*/g, '<b>$1</b>').replace(/\n/g, '<br>');

function slackHtml() {
  const parts = payload.blocks.map((b) => {
    if (b.type === 'header') return `<div class="h">${esc(b.text.text)}</div>`;
    if (b.type === 'section' && b.fields) return `<div class="fields">${b.fields.map((f) => `<div>${mrkdwn(f.text)}</div>`).join('')}</div>`;
    if (b.type === 'section') return `<div class="sec">${mrkdwn(b.text.text)}</div>`;
    if (b.type === 'context') return `<div class="ctx">${b.elements.map((e) => mrkdwn(e.text)).join(' ')}</div>`;
    return '';
  });
  return `<html><body style="margin:0;background:#f4ede4;font-family:Lato,Helvetica,Arial,sans-serif">
  <style>
   .wrap{width:760px;margin:28px auto;background:#fff;border-radius:8px;padding:18px 22px;box-shadow:0 1px 4px #0002;color:#1d1c1d;font-size:15px;line-height:1.4}
   .who{display:flex;gap:10px;align-items:center;margin-bottom:8px}.av{width:36px;height:36px;border-radius:6px;background:#0d1b2a;color:#2ec4b6;display:flex;align-items:center;justify-content:center;font-weight:700}
   .who b{font-size:15px}.who span{color:#616061;font-size:12px;margin-left:6px}.app{background:#e8e8e8;border-radius:3px;font-size:10px;padding:1px 4px;margin-left:6px;color:#616061}
   .h{font-size:18px;font-weight:700;margin:6px 0 10px}.fields{display:grid;grid-template-columns:1fr 1fr;gap:10px 24px;margin-bottom:12px}
   .sec{margin:10px 0}.ctx{color:#616061;font-size:12px;margin-top:10px}
  </style><div class="wrap"><div class="who"><div class="av">S</div><div><b>Store reports</b><span class="app">APP</span><span>7:00 AM</span></div></div>${parts.join('')}</div></body></html>`;
}

function coverHtml(dashDataUri) {
  const f = bench.full_run, i = bench.incremental_run;
  const sum = (r, k) => r.entities.reduce((a, e) => a + e[k], 0);
  const rec = Object.values(bench.reconciliation);
  const found = rec.reduce((a, r) => a + r.detected, 0), injected = rec.reduce((a, r) => a + r.injected, 0);
  const tiles = [
    [sum(i, 'rows_read').toLocaleString('en-US'), `rows read on the next run, vs ${sum(f, 'rows_read').toLocaleString('en-US')} on the first`],
    [`${found} of ${injected}`, 'planted payment mismatches caught'],
    [String(f.data_tests.passed), 'dbt data tests passing on every run'],
  ];
  const chips = ['Python', 'FastAPI', 'DuckDB', 'Postgres', 'dbt', 'Plotly', 'n8n', 'Slack'];
  return `<html><body style="margin:0;width:1600px;height:1200px;background:#0d1b2a;font-family:Inter,Helvetica,Arial,sans-serif;color:#fff;position:relative;overflow:hidden">
  <div style="position:absolute;left:90px;top:110px;width:660px">
    <div style="color:#2ec4b6;font-size:22px;letter-spacing:.14em;text-transform:uppercase;font-weight:600">Data engineering</div>
    <h1 style="font-size:78px;line-height:1.04;margin:22px 0 26px;font-weight:700">E-commerce Data Pipeline</h1>
    <p style="font-size:29px;line-height:1.4;color:#b8c7d6;margin:0">Store and payments APIs in, tested SQL models and a daily KPI dashboard out. Loads only what changed.</p>
    <div style="margin-top:56px;display:flex;flex-direction:column;gap:18px">
      ${tiles.map(([v, l]) => `<div style="background:#13283d;border-left:6px solid #2ec4b6;border-radius:10px;padding:20px 26px;display:flex;align-items:center;gap:22px"><div style="font-size:50px;font-weight:700;color:#2ec4b6;min-width:250px;white-space:nowrap">${v}</div><div style="font-size:23px;color:#d5e0ea;line-height:1.3">${l}</div></div>`).join('')}
    </div>
    <div style="margin-top:44px;display:flex;flex-wrap:wrap;gap:12px">${chips.map((c) => `<span style="border:1.5px solid #2ec4b6;color:#2ec4b6;border-radius:99px;padding:8px 20px;font-size:21px">${c}</span>`).join('')}</div>
  </div>
  <div style="position:absolute;left:800px;top:130px;width:740px;height:940px;background:#fff;border-radius:16px;box-shadow:0 30px 80px #000a;overflow:hidden">
    <img src="${dashDataUri}" style="width:740px;display:block">
  </div></body></html>`;
}

(async () => {
  const browser = await chromium.launch();
  const dash = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  await dash.goto('file://' + path.join(root, 'reports/dashboard.html'));
  await dash.waitForTimeout(2000);
  await dash.screenshot({ path: path.join(root, 'assets/dashboard.png'), fullPage: true });

  const slack = await browser.newPage({ viewport: { width: 820, height: 800 } });
  await slack.setContent(slackHtml());
  const h = await slack.evaluate(() => document.querySelector('.wrap').getBoundingClientRect().bottom + 28);
  await slack.screenshot({ path: path.join(root, 'assets/slack-summary.png'), clip: { x: 0, y: 0, width: 820, height: Math.ceil(h) } });

  const uri = 'data:image/png;base64,' + fs.readFileSync(path.join(root, 'assets/dashboard.png')).toString('base64');
  const cover = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  await cover.setContent(coverHtml(uri));
  await cover.waitForTimeout(500);
  await cover.screenshot({ path: path.join(root, 'assets/cover.png') });
  await browser.close();
})();
