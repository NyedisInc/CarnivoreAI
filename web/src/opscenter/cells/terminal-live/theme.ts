interface Manifest {
  id: string;
  cssVars?: Record<string, string>;
  xterm?: Record<string, string>;
}

export interface CellThemeContext {
  pinnedTheme: string | null;
}

interface ThemeClient {
  term?: { options: { theme?: Record<string, string>; minimumContrastRatio?: number } };
  _xtermOpacity?: { apply(theme: Record<string, string>): void };
  _cellThemeManifest?: () => Manifest | null;
}

interface ThemeHost {
  Themes?: {
    getSessionManifest(context: CellThemeContext): Manifest | null;
    getActiveTerminalManifest(): Manifest | null;
    onXtermThemeChange(callback: () => void): () => void;
  };
  ThemeVarWriter?: {
    applyVarDiff(style: CSSStyleDeclaration, previous: Record<string, string>, next: Record<string, string>):
      { values: Record<string, string> };
  };
  TerminalBackground?: { repaint(): unknown };
  TerminalBackgroundOpacity?: { minimumContrastRatioForXtermTheme(theme?: Record<string, string>): number };
}

export function bindTerminalTheme(
  terminal: unknown,
  element: HTMLElement,
  context: CellThemeContext,
  host: ThemeHost = globalThis as ThemeHost,
): () => void {
  const client = terminal as ThemeClient;
  const registry = host.Themes;
  if (!client || !registry?.getSessionManifest) return () => {};
  const frame = element.closest<HTMLElement>('[data-theme-scope]')
    ?? element.closest<HTMLElement>('.oc-frame') ?? element;
  const prior = client._cellThemeManifest;
  const resolve = (): Manifest | null => registry.getSessionManifest(context);
  client._cellThemeManifest = resolve;
  let values: Record<string, string> = {};
  let palette: Record<string, string> | undefined;

  function paint(): void {
    const manifest = resolve();
    if (manifest) frame.dataset.sessionTheme = manifest.id;
    else delete frame.dataset.sessionTheme;
    values = host.ThemeVarWriter?.applyVarDiff(frame.style, values, manifest?.cssVars ?? {}).values ?? {};
    if (client.term && manifest?.xterm && palette !== manifest.xterm) {
      palette = manifest.xterm;
      if (client._xtermOpacity) {
        client._xtermOpacity.apply(palette);
      } else {
        client.term.options.theme = palette;
        client.term.options.minimumContrastRatio =
          host.TerminalBackgroundOpacity?.minimumContrastRatioForXtermTheme(palette) ?? 1;
      }
    }
  }
  paint();
  host.TerminalBackground?.repaint();
  const unsubscribe = registry.onXtermThemeChange(paint);
  return () => {
    unsubscribe();
    if (client._cellThemeManifest !== resolve) return;
    client._cellThemeManifest = prior;
    host.ThemeVarWriter?.applyVarDiff(frame.style, values, {});
    delete frame.dataset.sessionTheme;
    const restored = (prior?.() ?? registry.getActiveTerminalManifest())?.xterm;
    if (client.term && restored) {
      if (client._xtermOpacity) {
        client._xtermOpacity.apply(restored);
      } else {
        client.term.options.theme = restored;
        client.term.options.minimumContrastRatio =
          host.TerminalBackgroundOpacity?.minimumContrastRatioForXtermTheme(restored) ?? 1;
      }
    }
    host.TerminalBackground?.repaint();
  };
}
