
export type TreeKind = 'project' | 'header' | 'sub' | 'row';

export function headerSteps(kind: TreeKind): number {
  return kind === 'header' ? 1 : kind === 'sub' ? 2 : 0;
}
