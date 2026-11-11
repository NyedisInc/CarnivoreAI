import { mount, unmount } from 'svelte';
import type { Fetcher } from './board-client';
import PublicBoard from './PublicBoard.svelte';
import { openBoard, saveDraft, sendPost, waitNext } from './session';

export function startPage(win: Window, target: HTMLElement, fetcher?: Fetcher): () => void {
  let app: ReturnType<typeof mount> | null = null;

  const draw = (): void => {
    if (app) unmount(app);
    target.replaceChildren();
    app = mount(PublicBoard, { target, props: {
      load: (revision) => openBoard(win, fetcher, revision), send: (route, body) => sendPost(win, route, body, fetcher),
      save: (body) => saveDraft(win, body, fetcher), wait: (revision) => waitNext(win, revision, fetcher),
    } });
  };

  const onHashChange = (): void => {
    if (win.location.hash.length > 1) draw();
  };

  draw();
  win.addEventListener('hashchange', onHashChange);
  return () => {
    win.removeEventListener('hashchange', onHashChange);
    if (app) unmount(app);
    app = null;
  };
}
