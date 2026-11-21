import { authFetch } from '../sdk';
import { BASE } from './board-model';

export interface BoardLook { theme: string; palette: Record<string, string> }

export async function fetchBoardLook(slug: string): Promise<BoardLook | null> {
  const out = await authFetch<{ look: BoardLook | null }>(`${BASE}/boards/${encodeURIComponent(slug)}/look`);
  return out.look;
}

export async function saveBoardLook(slug: string, look: BoardLook | null): Promise<void> {
  await authFetch(`${BASE}/boards/${encodeURIComponent(slug)}/look`, {
    method: 'PUT',
    body: JSON.stringify(look ?? { theme: null, palette: null }),
  });
}
