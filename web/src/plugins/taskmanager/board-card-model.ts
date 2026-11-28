
export const WORD_OF: Readonly<Record<string, string>> = {
  png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', webp: 'image', svg: 'svg',
  txt: 'text', log: 'text', patch: 'text', diff: 'text', md: 'markdown', markdown: 'markdown', csv: 'table', tsv: 'table',
  json: 'data', yaml: 'data', yml: 'data', toml: 'data', xml: 'data', html: 'web', htm: 'web', css: 'style', js: 'script',
  pdf: 'pdf', mp4: 'video', mov: 'video', webm: 'video', mp3: 'audio', wav: 'audio', docx: 'document', xlsx: 'spreadsheet', pptx: 'slides',
};

export function typeKey(name: string): string {
  const dot = name.lastIndexOf('.');
  const ext = dot > 0 ? name.slice(dot + 1).toLowerCase() : '';
  return `cplug.huddle.board.type.${WORD_OF[ext] ?? 'file'}`;
}
