
export interface MarkdownHint {
  syntax: string;
  key: string;
}

export const MARKDOWN_HINTS: readonly MarkdownHint[] = [
  { syntax: '# heading', key: 'markdown_editor.hint.heading' },
  { syntax: '**bold**', key: 'markdown_editor.hint.bold' },
  { syntax: '*italic*', key: 'markdown_editor.hint.italic' },
  { syntax: '`code`', key: 'markdown_editor.hint.code' },
  { syntax: '```', key: 'markdown_editor.hint.fence' },
  { syntax: '- item', key: 'markdown_editor.hint.bullet' },
  { syntax: '1. item', key: 'markdown_editor.hint.numbered' },
  { syntax: '> quote', key: 'markdown_editor.hint.quote' },
  { syntax: '---', key: 'markdown_editor.hint.rule' },
  { syntax: '[text](https://...)', key: 'markdown_editor.hint.link' },
];
