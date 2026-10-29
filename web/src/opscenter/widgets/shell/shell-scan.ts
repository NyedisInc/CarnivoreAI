
export type ShellRule = 'no-cell' | 'no-definition' | 'no-state' | 'no-binding' | 'no-shell';

function moduleScript(text: string): string {
  const open = /<script\b[^>]*\bmodule\b[^>]*>/.exec(text);
  if (!open) return '';
  const end = text.indexOf('</script>', open.index);
  return text.slice(open.index, end < 0 ? text.length : end);
}

export function scanShell(cell: string | null): ShellRule[] {
  if (cell === null) return ['no-cell'];
  const module = moduleScript(cell);
  const out: ShellRule[] = [];
  if (!/\bdefineWidget\s*\(/.test(module)) out.push('no-definition');
  if (!/\bstate\s*:/.test(module)) out.push('no-state');
  if (!/\buseWidget\s*\(/.test(cell.replace(module, ''))) out.push('no-binding');
  if (!/<WidgetShell\b/.test(cell)) out.push('no-shell');
  return out;
}
