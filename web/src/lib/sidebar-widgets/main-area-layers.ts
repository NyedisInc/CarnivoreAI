
export type LayerOrigin = 'menu' | 'sidebar' | 'tab';

export interface MainAreaLayer {
  origin: LayerOrigin;
  open: () => boolean;
  close: () => void;
}

const layers = new Set<MainAreaLayer>();

const ORDER: readonly LayerOrigin[] = ['menu', 'sidebar'];

export function registerMainAreaLayer(layer: MainAreaLayer): () => void {
  if (layer.origin === 'tab') return () => {};
  layers.add(layer);
  return () => void layers.delete(layer);
}

export function closeTopMainAreaLayer(): boolean {
  for (const origin of ORDER) {
    for (const layer of layers) {
      if (layer.origin === origin && layer.open()) {
        layer.close();
        return true;
      }
    }
  }
  return false;
}
