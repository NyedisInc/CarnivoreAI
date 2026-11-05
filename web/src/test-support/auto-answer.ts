
export interface AskedConfirm {
    title: string;
    message: string;
    details: string;
    okLabel: string;
    cancelLabel: string;
    variant: 'plain' | 'danger';
}

export interface AutoAnswer {
    asked: AskedConfirm[];
    stop(): void;
}

const text = (root: Element, selector: string): string => root.querySelector(selector)?.textContent ?? '';

export function autoAnswerConfirm(answer: boolean | ((asked: AskedConfirm) => boolean) = true): AutoAnswer {
    const asked: AskedConfirm[] = [];
    const seen = new WeakSet<Element>();
    const look = (): void => {
        // there is nothing
        if (typeof document === 'undefined') { observer.disconnect(); return; }
        for (const go of document.querySelectorAll<HTMLButtonElement>('[data-confirm-ok-go]')) {
            const dialog = go.closest('.modal-overlay');
            if (!dialog || seen.has(dialog)) continue;
            seen.add(dialog);
            const record: AskedConfirm = {
                title: text(dialog, '.text-prompt-modal__verb'),
                message: text(dialog, '[data-confirm-ok-message]'),
                details: text(dialog, '[data-confirm-ok-details]'),
                okLabel: go.textContent ?? '',
                cancelLabel: text(dialog, '[data-confirm-ok-cancel]'),
                variant: go.getAttribute('data-btn') === 'danger' ? 'danger' : 'plain',
            };
            asked.push(record);
            const yes = typeof answer === 'function' ? answer(record) : answer;
            queueMicrotask(() => (yes ? go : dialog.querySelector<HTMLButtonElement>('[data-confirm-ok-cancel]')!).click());
        }
    };
    const observer = new MutationObserver(look);
    observer.observe(document.body, { childList: true, subtree: true });
    return { asked, stop: () => observer.disconnect() };
}
