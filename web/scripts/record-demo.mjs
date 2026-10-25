// Portfolio UI recording only. All API responses and progress below are simulated.
// No Google/MEGA account or model is contacted. Never use this as provider acceptance evidence.
import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';

const directory = path.resolve('../docs');
await fs.mkdir(path.join(directory, 'images'), { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  recordVideo: { dir: path.resolve('../.state/demo-video'), size: { width: 1440, height: 1000 } },
});
const page = await context.newPage();
const conversation = { id: 'demo-conversation', title: 'Curso de Fotografia → MEGA' };
const destination = {
  id: 'demo-destination',
  name: 'Cursos no MEGA',
  kind: 'mega',
  path: 'Cursos',
};
const preferences = {
  destination_id: destination.id,
  default_action: 'download',
  export_gdocs: true,
  create_empty: true,
  auto_repair: true,
  reserve_bytes: 1073741824,
};
const baseJob = {
  id: 'd3a00000000000000000000000000001',
  status: 'running',
  stage: 'copy',
  revision: 1,
  message: 'Transferindo arquivos de demonstração.',
  current: 0,
  cancel_requested: false,
  spec: { mode: 'download', conversation_id: conversation.id, destination_id: destination.id },
  stats: { bytes: 0, totalBytes: 167772160, speed: 12582912 },
  items: [
    {
      name: 'Curso de Fotografia',
      count: 42,
      bytes: 167772160,
      destination: 'mega:Cursos/Curso de Fotografia',
      status: 'running',
      stage: 'copy',
      capacity: { status: 'sufficient', remote_free_bytes: 53687091200 },
    },
  ],
};
let messages = [];
let job = null;
await context.addInitScript(
  ({ baseJob }) => {
    window.__demoFinished = false;
    window.EventSource = class {
      constructor() {
        this.listeners = {};
        let tick = 0;
        this.timer = setInterval(() => {
          tick += 1;
          const snapshot = JSON.parse(JSON.stringify(baseJob));
          snapshot.revision = tick;
          snapshot.stats.bytes = Math.min(snapshot.stats.totalBytes, tick * 33554432);
          if (tick >= 5) snapshot.stage = 'check';
          if (tick >= 7) {
            snapshot.status = 'success';
            snapshot.stage = 'done';
            snapshot.stats = {};
            snapshot.message = 'Cópia de demonstração concluída. Auditoria por tamanho.';
            snapshot.items[0].status = 'success';
            snapshot.items[0].audit = { ok: true, coverage: 'size' };
            window.__demoFinished = true;
          }
          this.listeners.snapshot?.({ data: JSON.stringify(snapshot) });
          if (tick >= 7) {
            this.listeners.done?.({ data: JSON.stringify({ status: 'success' }) });
            this.close();
          }
        }, 1250);
      }
      addEventListener(name, callback) {
        this.listeners[name] = callback;
      }
      close() {
        clearInterval(this.timer);
      }
    };
    document.addEventListener('DOMContentLoaded', () => {
      const banner = document.createElement('div');
      banner.textContent = 'DEMONSTRAÇÃO DA INTERFACE · DADOS E PROGRESSO SIMULADOS';
      banner.style.cssText =
        'position:fixed;top:23px;left:50%;transform:translateX(-30%);z-index:100;padding:8px 13px;border:1px solid #e5d7ae;background:#fff7df;color:#8a6e32;border-radius:7px;font:10px sans-serif;letter-spacing:.5px';
      document.body.appendChild(banner);
    });
  },
  { baseJob },
);

await context.route('**/api/**', async (route) => {
  const endpoint = new URL(route.request().url()).pathname;
  const method = route.request().method();
  let body = {};
  if (endpoint === '/api/health')
    body = {
      ok: true,
      platform: 'win32',
      rclone: { installed: true, version: 'rclone v1.75.2' },
      connections: { google: true, mega: true, model: true },
    };
  else if (endpoint === '/api/destinations') body = [destination];
  else if (endpoint === '/api/preferences') body = preferences;
  else if (endpoint === '/api/conversations')
    body = method === 'POST' ? conversation : messages.length ? [conversation] : [];
  else if (endpoint.endsWith('/queue')) body = { items: [] };
  else if (endpoint.endsWith('/messages') && method === 'POST') {
    const input = route.request().postDataJSON();
    messages = [
      { id: 'user-demo', role: 'user', text: input.text },
      {
        id: 'assistant-demo',
        role: 'assistant',
        text: 'Encontrei 42 arquivos. O destino tem espaço disponível. Vou copiar para Cursos no MEGA e verificar o resultado por tamanho. Seus arquivos originais ficam preservados.',
        job_ids: [baseJob.id],
      },
    ];
    job = structuredClone(baseJob);
    body = messages[1];
  } else if (endpoint.endsWith('/messages')) body = messages;
  else if (endpoint === '/api/jobs') {
    if (job && (await page.evaluate(() => window.__demoFinished))) {
      job.status = 'success';
      job.stage = 'done';
      job.stats = {};
      job.message = 'Cópia de demonstração concluída. Auditoria por tamanho.';
      job.items[0].status = 'success';
      job.items[0].audit = { ok: true, coverage: 'size' };
    }
    body = job ? [job] : [];
  }
  await route.fulfill({ json: body });
});

await page.goto(process.env.DTA_DEMO_URL || 'http://127.0.0.1:8765');
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(2500);
await page.getByRole('button', { name: 'Preparar meu espaço' }).click();
await page.getByRole('button', { name: 'Preferências', exact: true }).click();
await page.waitForTimeout(3000);
await page.getByRole('button', { name: 'Fechar configuração' }).click();
await page
  .getByLabel('Mensagem', { exact: true })
  .pressSequentially(
    'Copie esta pasta para Cursos no MEGA: https://drive.google.com/drive/folders/DEMO_FOTOGRAFIA',
    { delay: 24 },
  );
await page.getByRole('button', { name: 'Enviar mensagem', exact: true }).click();
await page.waitForTimeout(4000);
await page.screenshot({ path: path.join(directory, 'images/demo-transfer.png') });
await page.waitForTimeout(7000);
const video = page.video();
await context.close();
await video.saveAs(path.join(directory, 'demo.webm'));
await browser.close();
console.log('Recorded docs/demo.webm — simulated UI, not a cloud integration test.');
