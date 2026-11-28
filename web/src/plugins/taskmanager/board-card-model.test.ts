import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { WORD_OF } from './board-card-model';

function serverExtensions(): string[] {
  const src = readFileSync(new URL('../../../../src/plugins/reviewboard/attachment_types.py', import.meta.url), 'utf8');
  const block = src.slice(src.indexOf('CLASS_BY_EXTENSION'), src.indexOf('ALLOWED_EXTENSIONS'));
  return [...block.matchAll(/"\.([a-z0-9]+)"/g)].map((m) => m[1]!);
}

describe('the board card type table', () => {
  it('names exactly the extensions the server allows', () => {
    const server = serverExtensions();
    expect(server.length).toBeGreaterThan(20);
    expect([...server].sort()).toEqual(Object.keys(WORD_OF).sort());
  });
});
