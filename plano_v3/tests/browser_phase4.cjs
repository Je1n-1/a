const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/jeanm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.PLANO_TEST_URL || 'http://127.0.0.1:5055';
const qa = JSON.parse(fs.readFileSync('docs/phase4-environment.json', 'utf8'));

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const evidence = { errors: [], steps: [] }, requests = [];
  const modal = page.locator('#common-dialog');
  page.on('pageerror', error => evidence.errors.push(error.message));
  page.on('request', request => requests.push(new URL(request.url()).pathname));
  const get = async route => (await page.request.get(base + '/api' + route)).json();
  const hasModule = name => requests.includes('/static/js/' + name + '.js');
  const ready = () => page.waitForFunction(() => document.querySelector('#analytics-results').getAttribute('aria-busy') === 'false');
  try {
    assert.equal((await get('/diagnostics')).path, qa.browser_database, 'Use apenas a base de verificação.');
    requests.length = 0;
    await page.goto(base);
    await page.waitForFunction(() => document.querySelector('#today-total').textContent !== '—');
    assert.deepEqual(requests.filter(url => url.startsWith('/api/')), ['/api/today']);
    assert.equal(hasModule('manual-session'), false);
    assert.equal(hasModule('curriculum-import'), false);
    assert.equal(hasModule('session-editor'), false);
    assert.equal(requests.some(url => /planning|planejamento/.test(url)), false);
    requests.length = 0;
    await page.evaluate(() => { window.dispatchEvent(new Event('focus')); document.dispatchEvent(new Event('visibilitychange')); });
    await page.waitForTimeout(350);
    assert.deepEqual(requests.filter(url => url.startsWith('/api/')), ['/api/today']);
    await page.locator('#today-subject').selectOption('free');
    await page.locator('#free-title').fill('Verificação de requisições');
    await page.locator('#start-button').click();
    await page.locator('[data-action=pause]').waitFor();
    requests.length = 0;
    await page.locator('[data-action=pause]').click();
    await page.locator('[data-action=resume]').waitFor();
    await page.waitForTimeout(150);
    assert.equal(requests.filter(url => url.startsWith('/api/')).length, 1);
    assert.match(requests.find(url => url.startsWith('/api/')), /\/pause$/);
    await page.locator('[data-action=cancel]').click();
    await modal.locator('button[type=submit]').click();
    await modal.waitFor({ state: 'hidden' });
    evidence.steps.push('Hoje abre com uma API; retorno à aba coalescido; pausa não dispara leituras redundantes.');

    await page.goto(base + '/subjects');
    await page.locator('[data-new-course]').waitFor();
    assert.equal(hasModule('curriculum-import'), false);
    await page.locator('#new-course').click();
    await modal.locator('[name=name]').fill('Grade sintética da Fase 4');
    await modal.locator('button[type=submit]').click();
    await modal.waitFor({ state: 'hidden' });
    for (let attempt = 0; attempt < 2; attempt++) {
      await page.locator('[data-import]').first().click();
      await page.locator('#import-dialog [name=file]').setInputFiles('static/downloads/modelo_grade_curricular.xlsx');
      await page.locator('#import-dialog button[type=submit]').click();
      await page.locator('#selection-count').waitFor();
      assert.equal(await page.locator('[data-field=include]:checked').count(), 0);
      assert.equal((await get('/subjects')).length, attempt * 3);
      await page.locator('#select-all').check();
      await page.locator('#confirm-import').click();
      await page.locator('#import-dialog').waitFor({ state: 'hidden' });
      assert.equal((await get('/subjects')).length, 3);
    }
    assert.equal(hasModule('curriculum-import'), true);
    evidence.steps.push('Importador carregado ao abrir; XLSX com seleção explícita; reimportação não duplica três disciplinas.');

    requests.length = 0;
    await page.goto(base + '/analytics?start=2026-10-01&end=2026-10-10');
    await ready();
    assert.equal(await page.locator('.chart-card').count(), 2);
    assert.equal(hasModule('session-editor'), false);
    assert.equal(hasModule('manual-session'), false);
    await page.locator('[data-edit]').first().click();
    await modal.locator('[name=reason]').fill('Conferência da Fase 4');
    await modal.locator('[name=note]').fill('Nota alterada em banco sintético.');
    await modal.locator('button[type=submit]').click();
    await modal.waitFor({ state: 'hidden' });
    await ready();
    assert.equal(hasModule('session-editor'), true);
    assert.equal(hasModule('manual-session'), false);
    await page.locator('[data-audit]').first().click();
    await modal.locator('.audit-entry').waitFor();
    assert.match(await modal.textContent(), /Conferência da Fase 4/);
    await modal.locator('[data-close]').first().click();
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: 'docs/phase4-analytics-mobile.png', fullPage: true });
    evidence.steps.push('Dois gráficos; editor carregado ao corrigir; alteração salva e auditável; 390 px sem transbordamento.');
    assert.deepEqual(evidence.errors, []);
    fs.writeFileSync('docs/phase4-ui.json', JSON.stringify(evidence, null, 2));
    console.log(JSON.stringify(evidence, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
