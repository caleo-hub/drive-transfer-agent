import { describe, expect, it } from 'vitest';
import { bytes, finalStates, stageLabel } from './api';

describe('progress presentation', () => {
  it('does not treat an unknown size as zero or unlimited', () => {
    expect(bytes(undefined)).toBe('não informado');
    expect(bytes(null)).toBe('não informado');
    expect(bytes(-1)).toBe('não informado');
    expect(bytes(0)).toBe('0 B');
    expect(bytes(1024)).toBe('1 KiB');
  });
  it('distinguishes interrupted work and verification from transfer completion', () => {
    expect(finalStates).toContain('interrupted');
    expect(finalStates).not.toContain('running');
    expect(stageLabel.check).toBe('Verificando arquivos');
    expect(stageLabel.inspect).toBe('Consultando origem');
  });
});
