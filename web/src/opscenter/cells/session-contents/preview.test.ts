import { describe, expect, test } from 'vitest';
import { canPreview, headLines } from './preview';

const file = (open_path: string | null, open_root: string | null = 'user') => ({ open_root, open_path });

describe('canPreview', () => {
  test('prose kinds with an openable file may be read', () => {
    expect(['instructions', 'skills', 'agents', 'commands', 'output_styles', 'prompts'].map((k) => canPreview(k, file('a.md')))).toEqual([true, true, true, true, true, true]);
  });

  test('settings, mcp, hooks, plugins and profiles are never read', () => {
    expect(['settings', 'mcp', 'hooks', 'plugins', 'profiles'].map((k) => canPreview(k, file('settings.json')))).toEqual([false, false, false, false, false]);
  });

  test('an item with no file, and a credential shaped name, are never read', () => {
    expect(canPreview('skills', file(null, null))).toBe(false);
    expect(['.env', 'sub/.env.local', 'auth.json', 'credentials.json', 'x/.claude.json', 'api_token.md', 'id.pem'].map((n) => canPreview('instructions', file(n)))).toEqual(Array(7).fill(false));
  });
});

describe('headLines', () => {
  test('keeps the first lines, trims the ends and cuts a long line', () => {
    expect(headLines('a  \nb\nc', 2)).toEqual(['a', 'b']);
    expect(headLines('x'.repeat(500))[0]).toHaveLength(160);
  });
});
