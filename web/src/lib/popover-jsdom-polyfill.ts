export function installPopoverPolyfill(): void {
    const proto = window.HTMLElement.prototype as unknown as {
        showPopover?: () => void;
        hidePopover?: () => void;
        togglePopover?: (force?: boolean) => boolean;
    };
    if (!proto.showPopover) proto.showPopover = function (): void {};
    if (!proto.hidePopover) proto.hidePopover = function (): void {};
    if (!proto.togglePopover) {
        proto.togglePopover = function (): boolean {
            return true;
        };
    }
}
