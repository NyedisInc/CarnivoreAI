import { describe, expect, it } from 'vitest';
import { parseMarkdown, type Block } from '../../opscenter/cells/notes/markdown';
import { MARKDOWN_HINTS } from './hints';

function firstBlock(syntax: string): Block | undefined {
  return parseMarkdown(syntax === '```' ? '```\nx\n```' : syntax)[0];
}

describe('the markdown cheat sheet', () => {
  it('lists only constructs the preview renders', () => {
    for (const hint of MARKDOWN_HINTS) {
      const block = firstBlock(hint.syntax.replace('https://...', 'https://example.com'));
      const literal = block?.kind === 'paragraph' && block.children.length === 1 && block.children[0]?.kind === 'text';
      expect(literal, hint.syntax).toBe(false);
    }
  });

  it('NEGATIVE CONTROL: a construct the preview does not know is a literal paragraph, so the check can fail', () => {
    const block = firstBlock('| a | b |');
    expect(block?.kind === 'paragraph' && block.children[0]?.kind === 'text').toBe(true);
  });
});
