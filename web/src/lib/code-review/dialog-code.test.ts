import { describe, expect, it } from 'vitest';
import { dialogCode } from './dialog-code';
import { itemCode } from './risk';

const CLAUDE_BODY = [
  ' Bash command',
  ' Tip: auto mode handles these prompts for you — choose "switch to auto mode" below',
  '',
  '   touch rigfile',
  '   make a file',
  '',
  ' Do you want to proceed?',
  ' ❯ 1. Yes',
  '   2. Yes, and always allow access to /tmp/work from this project',
  '   3. Yes, and switch to auto mode · auto mode handles these prompts for you',
  '   4. No',
].join('\n');
const CLAUDE_ROWS = ['Yes', 'Yes, and always allow access to /tmp/work from this project', 'Yes, and switch to auto mode', 'No']
  .map((label) => ({ label, role: 'option' as const }));

const WRAPPED_BODY = [
  ' Bash command',
  ' Tip: auto mode handles these prompts for you — choose "switch to auto mode"',
  ' below',
  '   touch rigfile-with-a-fairly-long-name.txt',
  '   make a file',
  ' Do you want to',
  ' proceed?',
  ' ❯ 1. Yes',
  '   2. No',
].join('\n');

const CODEX_BODY = [
  '  >_ OpenAI Codex (v0.159.2)',
  '     /tmp/work',
  '  Speak, friend, and enter a prompt.',
  '› RIG:run please',
  '• Running touch rigfile',
  '  Would you like to run the following command?',
  '  Environment: local',
  '  Reason: rig wants a file',
  '  $ touch rigfile',
  '› 1. Yes, proceed (y)',
  "  2. Yes, and don't ask again for commands that start with `touch rigfile` (p)",
  '  3. No, and tell Codex what to do differently (esc)',
].join('\n');

describe('dialogCode', () => {
  it('claude permission: keeps the command and its description, drops header, tip, question and options', () => {
    expect(dialogCode({ body: CLAUDE_BODY, question: 'Do you want to proceed?', rows: CLAUDE_ROWS })).toBe('touch rigfile\nmake a file');
  });
  it('finds the option block from structured rows, and by pattern when there are none', () => {
    const noRows = dialogCode({ body: CLAUDE_BODY, question: 'Do you want to proceed?' });
    expect(noRows).toBe('touch rigfile\nmake a file');
  });
  it('handles a wrapped tip and a wrapped question', () => {
    expect(dialogCode({ body: WRAPPED_BODY, question: 'Do you want to proceed?' }))
      .toBe('touch rigfile-with-a-fairly-long-name.txt\nmake a file');
  });
  it('codex: drops the banner, question, Environment and Reason lines, keeps the command line', () => {
    expect(dialogCode({ body: CODEX_BODY, question: 'Would you like to run the following command?' }).split('\n').pop()).toBe('$ touch rigfile');
    expect(dialogCode({ body: CODEX_BODY, question: 'Would you like to run the following command?' })).toBe('$ touch rigfile');
  });
  it('keeps multi-line scripts and inner blank lines exactly, numbering from the first code line', () => {
    const body = ' Bash command\n   set -e\n\n     rm -rf build\n Do you want to proceed?\n 1. Yes\n 2. No';
    const code = dialogCode({ body, question: 'Do you want to proceed?' });
    expect(code).toBe('set -e\n\n  rm -rf build');
  });
  it('returns an empty string for an empty body', () => {
    expect(dialogCode({ body: '', question: 'x' })).toBe('');
  });
});

describe('itemCode over a real permission body', () => {
  it('no longer carries the question or option rows', () => {
    const code = itemCode({ id: 'a', source: 'dialog', kind: 'permission', body: CLAUDE_BODY, question: 'Do you want to proceed?', rows: CLAUDE_ROWS });
    expect(code).toBe('touch rigfile\nmake a file');
  });
});
