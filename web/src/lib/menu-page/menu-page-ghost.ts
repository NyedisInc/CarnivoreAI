/* nothing at all there is nothing */
import { motionReduced } from '../motion/motion';

const GHOST_LIMIT_MS = 600;

export function slideBack(removed: readonly HTMLElement[], doc: Document = document): HTMLElement[] {
    const win = doc.defaultView;
    if (!win || !doc.body || motionReduced()) return [];
    const root = win.getComputedStyle(doc.documentElement);
    const surfaceLeft = parseFloat(root.getPropertyValue('--menu-surface-left'));
    if (!doc.body.classList.contains('menu-page-surface') || Number.isNaN(surfaceLeft)) return [];
    const px = (name: string): string => `${parseFloat(root.getPropertyValue(name)) || 0}px`;
    const ghosts: HTMLElement[] = [];
    for (const node of removed) {
        if (!node.classList.contains('oc-page') || node.classList.contains('oc-page--embedded')) continue;
        const ghost = node.cloneNode(true) as HTMLElement;
        const offset = parseFloat(node.style.getPropertyValue('--oc-drawer-offset')) || 0;
        ghost.classList.add('oc-page--ghost');
        ghost.setAttribute('inert', '');
        ghost.setAttribute('aria-hidden', 'true');
        ghost.removeAttribute('id');
        ghost.style.top = px('--menu-surface-top');
        ghost.style.bottom = px('--menu-surface-bottom');
        ghost.style.left = `${surfaceLeft + offset}px`;
        ghost.style.setProperty('--menu-surface-left', `${surfaceLeft}px`);
        const drop = (): void => ghost.remove();
        ghost.addEventListener('animationend', drop, { once: true });
        win.setTimeout(drop, GHOST_LIMIT_MS);
        doc.body.append(ghost);
        ghosts.push(ghost);
    }
    return ghosts;
}
