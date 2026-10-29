import { inTerminal, layerShowing, ownsEscape } from '../sidebar-widgets/escape-guards';
import { closeTopMainAreaLayer } from '../sidebar-widgets/main-area-layers';

export interface EscapeDeps {
    pageOpen: () => boolean;
    close: () => void;
}

export function handleMenuPageEscape(event: KeyboardEvent, deps: EscapeDeps, doc: Document = document): boolean {
    if (event.key !== 'Escape' || event.defaultPrevented || event.isComposing) return false;
    if (inTerminal(event.target) || layerShowing(doc) || ownsEscape(event.target)) return false;
    if (deps.pageOpen()) {
        event.preventDefault();
        deps.close();
        return true;
    }
    if (!closeTopMainAreaLayer()) return false;
    event.preventDefault();
    return true;
}

export function initMenuPageEscape(doc: Document, deps: EscapeDeps): () => void {
    const onKey = (event: KeyboardEvent): void => {
        handleMenuPageEscape(event, deps, doc);
    };
    doc.addEventListener('keydown', onKey);
    return () => doc.removeEventListener('keydown', onKey);
}
