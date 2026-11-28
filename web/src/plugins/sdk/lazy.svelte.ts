import type { Component } from 'svelte';
import { mountAtAnchor } from '../../lib/mount';

export function lazyComponent<P extends Record<string, any> = Record<string, any>>(
  loader: () => Promise<{ default: Component<P, any> }>,
): Component<P> {
  let promise: Promise<{ default: Component<P, any> }> | null = null;
  const load = (): Promise<{ default: Component<P, any> }> => {
    promise ??= loader();
    return promise;
  };
  return ((anchor: Node, props: P) => {
    let dispose: (() => void) | null = null;
    $effect(() => {
      let active = true;
      void load().then((mod) => {
        if (!active || !anchor.parentNode) return;
        dispose = mountAtAnchor(
          anchor.parentNode as Element,
          anchor,
          mod.default as Component<Record<string, unknown>, Record<string, unknown>>,
          props as Record<string, unknown>,
        );
      });
      return () => {
        active = false;
        if (dispose) {
          const stop = dispose;
          dispose = null;
          stop();
        }
      };
    });
    return {};
  }) as unknown as Component<P>;
}
