let iconUrls = $state<Record<string, string>>({});

export function setPluginIconUrl(kind: string, url: string | null | undefined): void {
  if (url) {
    if (iconUrls[kind] === url) return;
    iconUrls = { ...iconUrls, [kind]: url };
  } else if (kind in iconUrls) {
    const next = { ...iconUrls };
    delete next[kind];
    iconUrls = next;
  }
}

export function pluginIconUrl(widget: string | null | undefined): string | null {
  if (!widget) return null;
  const kind = widget.includes(':') ? widget.split(':', 1)[0] : widget;
  return (kind && iconUrls[kind]) || iconUrls[widget] || null;
}
