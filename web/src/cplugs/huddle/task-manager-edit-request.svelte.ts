export const editRequest = $state<{ title: number | null }>({ title: null });

export function requestEdit(which: 'title', id: number): void {
  editRequest[which] = id;
}

export function takeEdit(which: 'title', id: number): boolean {
  if (editRequest[which] !== id) return false;
  editRequest[which] = null;
  return true;
}
