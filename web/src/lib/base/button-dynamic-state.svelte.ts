export function dynamicState(): { flag: boolean; items: string[] } {
  const s = $state({ flag: false, items: ['alpha', 'beta'] });
  return s;
}
