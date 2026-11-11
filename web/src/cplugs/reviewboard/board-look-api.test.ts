import { beforeEach, describe, expect, it, vi } from 'vitest';

const net = vi.hoisted(() => ({ authFetch: vi.fn() }));
vi.mock('../sdk', async (importOriginal) => ({ ...(await importOriginal<typeof import('../sdk')>()), ...net }));

import { fetchBoardLook, saveBoardLook } from './board-look-api';

beforeEach(() => net.authFetch.mockReset());

describe('the board look calls', () => {
  it('reads the board\'s own theme from GET /boards/{slug}/look and answers null when none', async () => {
    net.authFetch.mockResolvedValueOnce({ look: { theme: 'dracula', palette: { '--oc-orange': 'x' } } }).mockResolvedValueOnce({ look: null });
    expect(await fetchBoardLook('20261013-bar')).toEqual({ theme: 'dracula', palette: { '--oc-orange': 'x' } });
    expect(await fetchBoardLook('20261013-bar')).toBeNull();
    expect(net.authFetch).toHaveBeenCalledWith('/cplugs/reviewboard/boards/20261013-bar/look');
  });

  it('keeps a theme with its palette by PUT, and clears with nulls', async () => {
    net.authFetch.mockResolvedValue({ look: null });
    await saveBoardLook('20261013-bar', { theme: 'carnivore-light', palette: { '--oc-ground-page': 'rgb(255, 255, 255)' } });
    await saveBoardLook('20261013-bar', null);
    expect(net.authFetch).toHaveBeenNthCalledWith(1, '/cplugs/reviewboard/boards/20261013-bar/look',
      { method: 'PUT', body: JSON.stringify({ theme: 'carnivore-light', palette: { '--oc-ground-page': 'rgb(255, 255, 255)' } }) });
    expect(net.authFetch).toHaveBeenNthCalledWith(2, '/cplugs/reviewboard/boards/20261013-bar/look', { method: 'PUT', body: JSON.stringify({ theme: null, palette: null }) });
  });
});
