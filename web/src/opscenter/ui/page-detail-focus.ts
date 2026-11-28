
const LIST_SIBLINGS = ['.oc-page__col', '.oc-page__scroll', '.oc-page__fill'];

export function detailReplacesList(region: HTMLElement): boolean {
    const parent = region.parentElement;
    if (!parent) return false;
    const list = Array.from(parent.children).find(
        (child): child is HTMLElement => child !== region && child instanceof HTMLElement && LIST_SIBLINGS.some((sel) => child.matches(sel)),
    );
    return !!list && getComputedStyle(list).display === 'none';
}

export function detailFocus(replaces: (region: HTMLElement) => boolean = detailReplacesList): (region: HTMLElement) => () => void {
    return (region) => {
        const opener = document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null;
        const moved = replaces(region);
        if (moved) region.querySelector<HTMLElement>('[data-detail-focus]')?.focus();
        return () => {
            if (!moved || !opener) return;
            const hadFocus = region.contains(document.activeElement);
            queueMicrotask(() => {
                const dropped = !document.activeElement || document.activeElement === document.body;
                if ((hadFocus || dropped) && opener.isConnected) opener.focus();
            });
        };
    };
}
