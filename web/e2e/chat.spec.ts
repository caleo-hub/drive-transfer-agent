import { test, expect } from '@playwright/test';
import os from 'node:os';
import path from 'node:path';

test('transfer plan: shows exact paths, separates preflight and approval, rejects stale plan', async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.route('https://fonts.googleapis.com/**', (route) => route.abort());
  await page.setViewportSize({ width: 390, height: 844 });
  const chat = await (
    await request.post('/api/conversations', { headers: { 'x-dta-request': '1' } })
  ).json();
  const plan = {
    id: 'test-plan',
    status: 'ready',
    requires_approval: true,
    approved: false,
    stale: false,
    destination: {
      id: 'test-dest',
      name: 'ANEST REVIEW 2026',
      kind: 'mega',
      path: 'ANEST REVIEW 2026',
    },
    items: [34, 35, 36, 37, 38].map((n) => ({
      source_id: String(n),
      name: `${n} – Pasta selecionada`,
      target: `mega:ANEST REVIEW 2026/${n} – Pasta selecionada`,
    })),
    steps: ['Conferir origens', 'Consultar espaço', 'Copiar e auditar'],
    note: 'Mantém o nome de cada pasta selecionada.',
  };
  const actions: string[] = [];
  await page.route(`**/api/conversations/${chat.id}/messages`, (route) =>
    route.fulfill({ json: [{ id: 'plan-message', role: 'assistant', text: '', plan }] }),
  );
  await page.route(`**/api/conversations/${chat.id}/plans/test-plan/*`, (route) => {
    actions.push(route.request().url().split('/').pop()!);
    if (actions.at(-1) === 'execute') plan.status = 'started';
    return route.fulfill({ json: { job_id: 'test-only', copied: false } });
  });
  await page.addInitScript((id) => localStorage.setItem('dta-conversation', id), chat.id);
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const card = page.getByRole('region', { name: 'Plano de transferência' });
  await expect(card.locator('.plan-origins li')).toHaveCount(5);
  await expect(card).toContainText('mega:ANEST REVIEW 2026/34 – Pasta selecionada');
  await card.getByRole('button', { name: 'Consultar tamanho e espaço' }).click();
  await expect(card.getByRole('button', { name: 'Aprovar plano e iniciar' })).toBeEnabled();
  expect(actions).toEqual(['preflight']);
  await card.getByRole('button', { name: 'Aprovar plano e iniciar' }).click();
  await expect(card).toContainText('Plano enviado ao executor');
  expect(actions).toEqual(['preflight', 'execute']);
  plan.status = 'ready';
  plan.stale = true;
  await page.reload();
  await expect(card).toContainText('O pedido mudou');
  await expect(card.getByRole('button')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await request.delete(`/api/conversations/${chat.id}`, { headers: { 'x-dta-request': '1' } });
});

for (const mobile of [false, true]) {
  test(`conversation management: archive, restore and delete${mobile ? ' on mobile' : ''}`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.setViewportSize(
      mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 },
    );
    await page.goto('/');
    if (mobile) await page.getByRole('button', { name: 'Abrir menu' }).click();
    await page.getByRole('button', { name: 'Nova conversa' }).click();
    const title = 'Conversa para organizar ' + Date.now();
    await page.getByLabel('Mensagem', { exact: true }).fill(title);
    await page.getByRole('button', { name: 'Enviar mensagem', exact: true }).click();
    await expect(page.getByText('Vamos preparar o aplicativo.', { exact: false })).toBeVisible();
    if (mobile) await page.getByRole('button', { name: 'Abrir menu' }).click();
    const active = page.getByRole('navigation', { name: 'Conversas ativas' });
    const current = active.locator('.conversation-row.selected');
    await expect(current.locator('.conversation-open')).toHaveText(title);
    await current.getByRole('button', { name: 'Opções de ' + title }).click();
    await page.getByRole('menuitem', { name: 'Arquivar conversa' }).click();
    await expect(active.getByRole('button', { name: title, exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: 'Ver conversas arquivadas' }).click();
    const archived = page.getByRole('navigation', { name: 'Conversas arquivadas' });
    await archived.getByRole('button', { name: title, exact: true }).click();
    await expect(page.getByLabel('Mensagem', { exact: true })).toBeDisabled();
    await page.reload();
    await expect(page.getByLabel('Mensagem', { exact: true })).toBeDisabled();
    await page.getByRole('button', { name: 'Restaurar conversa', exact: true }).click();
    await expect(page.getByLabel('Mensagem', { exact: true })).toBeEnabled();
    await expect(page.getByText('Vamos preparar o aplicativo.', { exact: false })).toBeVisible();
    if (mobile) await page.getByRole('button', { name: 'Abrir menu' }).click();
    await active.getByRole('button', { name: 'Opções de ' + title }).click();
    await page.getByRole('menuitem', { name: 'Excluir conversa' }).click();
    const dialog = page.getByRole('dialog', { name: 'Excluir conversa?' });
    await expect(dialog).toContainText(title);
    await dialog.getByRole('button', { name: 'Cancelar', exact: true }).click();
    await expect(active.getByRole('button', { name: title, exact: true })).toBeVisible();
    await active.getByRole('button', { name: 'Opções de ' + title }).click();
    await page.getByRole('menuitem', { name: 'Excluir conversa' }).click();
    await dialog.getByRole('button', { name: 'Excluir permanentemente' }).click();
    await expect(dialog).not.toBeVisible();
    await expect(active.getByRole('button', { name: title, exact: true })).toHaveCount(0);
    await page.reload();
    expect(await page.evaluate(() => localStorage.getItem('dta-conversation'))).toBeNull();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      mobile ? 390 : 1440,
    );
    expect(errors).toEqual([]);
  });
}

test('onboarding, destinations and conversation work before configuring the model', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('no lugar certo');
  await page.getByRole('button', { name: 'Preparar meu espaço' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: 'OpenAI', exact: true }).click();
  await expect(page.getByLabel('Chave da API')).toHaveAttribute('type', 'password');
  await page.getByRole('dialog').getByRole('button', { name: 'Google Drive', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Preparar conexão Google' })).toBeVisible();
  await page.getByRole('button', { name: 'Destinos', exact: true }).click();
  const name = 'Destino de teste ' + Date.now();
  await page.getByLabel('Nome amigável').fill(name);
  await page.getByLabel('Caminho', { exact: true }).fill(path.join(os.tmpdir(), 'dta-e2e'));
  await page.getByRole('button', { name: 'Cadastrar destino' }).click();
  await expect(page.getByRole('status')).toContainText('Destino cadastrado');
  await page.getByRole('button', { name: 'Preferências', exact: true }).click();
  await page.getByLabel('Destino padrão', { exact: true }).selectOption({ label: name });
  await page.getByRole('button', { name: 'Salvar preferências' }).click();
  await expect(page.getByRole('status')).toContainText('Preferências salvas');
  await page.getByRole('button', { name: 'Fechar configuração' }).click();
  await page.getByLabel('Mensagem', { exact: true }).fill('Olá, quero organizar meus arquivos');
  await page.getByRole('button', { name: 'Enviar mensagem', exact: true }).click();
  await expect(page.getByText('Vamos preparar o aplicativo.', { exact: false })).toBeVisible();
  await page.reload();
  await expect(page.getByText('Vamos preparar o aplicativo.', { exact: false })).toBeVisible();
  expect(errors).toEqual([]);
});

test('mobile layout stays usable without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByLabel('Mensagem', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole('button', { name: 'Abrir menu' }).click();
  await expect(page.getByRole('button', { name: 'Nova conversa' })).toBeVisible();
  await page.getByRole('button', { name: 'Fechar menu' }).click();
  await page.screenshot({ path: '../docs/images/mobile.png', fullPage: true });
});

test('desktop welcome screenshot', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/');
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: '../docs/images/overview.png', fullPage: true });
});
