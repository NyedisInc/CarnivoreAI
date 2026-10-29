export function railBodyKey(cell: { id: string }, target: string | null, instance: string | null): string {
  return `session-rail:${target ? `${cell.id}@${target}` : cell.id}${instance ? `#${instance}` : ''}`;
}
