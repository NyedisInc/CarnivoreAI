import { describe, expect, test, vi } from 'vitest';
import type { Component } from 'svelte';
import { GlanceRegistry, type GlanceRenderer } from './glance';
import { declaredGlanceHeight, glanceHeightOf, GlanceDeclarationError } from '../../opscenter/widgets/glance-declarations';

const renderer: GlanceRenderer = { tiles: () => [], component: (() => undefined) as unknown as Component<never> as never };
const declared = (widget: string): number | null => (widget === 'core.a' ? 72 : null);

describe('the glance registry', () => {
  test('hands back the renderer with the declared height', () => {
    const registry = new GlanceRegistry(declared);
    expect(registry.register('core.a', renderer)).toBe(true);
    expect(registry.get('core.a')).toMatchObject({ height: 72, tiles: renderer.tiles });
  });

  test('draws the icon (null) for a widget with no renderer or no declaration', () => {
    const registry = new GlanceRegistry(declared);
    expect(registry.get('core.a')).toBeNull();
    expect(registry.get('core.b')).toBeNull();
  });

  test('refuses a renderer for an undeclared widget, and a second one', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const registry = new GlanceRegistry(declared);
    expect(registry.register('core.b', renderer)).toBe(false);
    expect(registry.get('core.b')).toBeNull();
    expect(registry.register('core.a', renderer)).toBe(true);
    expect(registry.register('core.a', renderer)).toBe(false);
    warn.mockRestore();
  });
});

describe('the glance declaration', () => {
  test('the shipped file declares the provider widget and no other', () => {
    expect(declaredGlanceHeight('core.ledger')).toBe(36);
    expect(declaredGlanceHeight('core.notes')).toBeNull();
  });

  test('refuses a malformed height', () => {
    for (const glance of [{ height: 5 }, { height: 999 }, { height: 70.5 }, {}, { height: 72, w: 1 }, null]) {
      expect(() => glanceHeightOf({ id: 'core.x', glance })).toThrow(GlanceDeclarationError);
    }
    expect(glanceHeightOf({ id: 'core.x' })).toBeNull();
  });
});
