/** @vitest-environment jsdom */
import { expect, test, vi } from 'vitest';
import { artDensity, setArtDensity, validDensity } from './density.svelte';

test('rejects invalid stored or event values and keeps all supported levels', () => {
  for (const level of ['minimal', 'balanced', 'full']) expect(validDensity(level)).toBe(level);
  for (const value of [null, '', 'huge', {}, '<script>']) expect(validDensity(value)).toBe('balanced');
});

test('updates decoration without replacing terminal nodes and tolerates denied storage', () => {
  const terminal = document.createElement('div');
  terminal.id = 'test-terminal';
  document.body.append(terminal);
  setArtDensity('full');
  expect(document.documentElement.dataset.artDensity).toBe('full');
  expect(localStorage.getItem('carnivore.art-density.v1')).toBe('full');
  expect(localStorage.getItem('cloude.art-density.v1')).toBe('full');
  const denied = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('blocked'); });
  expect(() => setArtDensity('minimal')).not.toThrow();
  expect(artDensity.value).toBe('minimal');
  expect(document.getElementById('test-terminal')).toBe(terminal);
  denied.mockRestore();
  terminal.remove();
});
