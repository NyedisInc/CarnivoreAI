/* at the gesture */
import { saveBoardLook, fetchBoardLook } from './board-look-api';
import { tokensFor } from './board-theme';

export class BoardLookState {
  choice = $state('');
  private generation = 0;

  open(slug: string | null, repaint: () => void): () => void {
    this.choice = '';
    const mine = ++this.generation;
    if (slug) {
      fetchBoardLook(slug).then((found) => {
        if (mine !== this.generation) return;
        this.choice = found?.theme ?? '';
        repaint();
      }, () => {  });
    }
    return () => { if (this.generation === mine) this.generation += 1; };
  }

  pick(slug: string | null, id: string, repaint: () => void): void {
    this.generation += 1;
    this.choice = id;
    repaint();
    const palette = id ? tokensFor(id) : null;
    if (slug) void saveBoardLook(slug, id && palette ? { theme: id, palette } : null).catch(() => {  });
  }
}
