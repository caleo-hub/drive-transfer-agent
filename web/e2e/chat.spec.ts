import { test, expect } from '@playwright/test';
import os from 'node:os';
import path from 'node:path';

test('onboarding, destinations and conversation work before configuring the model', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('no lugar certo');
  await page.getByRole('button', { name: 'Preparar meu espaço' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: 'Gemini', exact: true }).click();
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
