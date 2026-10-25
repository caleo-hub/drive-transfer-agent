export async function api<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-DTA-Request': '1' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(
      data.message || 'Não foi possível concluir o pedido. Confira a conexão com o aplicativo.',
    );
  }
  return response.json();
}

export function bytes(value?: number | null): string {
  if (value === undefined || value === null || value < 0) return 'não informado';
  if (value === 0) return '0 B';
  const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), 4);
  return `${(value / 1024 ** unit).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} ${['B', 'KiB', 'MiB', 'GiB', 'TiB'][unit]}`;
}
export const finalStates = ['success', 'failed', 'attention', 'cancelled', 'interrupted'];
export const statusLabel: Record<string, string> = {
  pending: 'Preparada',
  running: 'Em andamento',
  success: 'Concluída',
  failed: 'Falhou',
  attention: 'Precisa de atenção',
  cancelled: 'Cancelada',
  interrupted: 'Interrompida',
};
export const stageLabel: Record<string, string> = {
  pending: 'Preparando',
  inspect: 'Consultando origem',
  copy: 'Transferindo',
  check: 'Verificando arquivos',
  repair: 'Reparando diferenças',
  done: 'Finalizada',
};
