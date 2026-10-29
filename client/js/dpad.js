
class DPad {
    constructor() {
        this.keys = {
            UP: '\x1b[A',
            DOWN: '\x1b[B',
            RIGHT: '\x1b[C',
            LEFT: '\x1b[D',
            ESC: '\x1b',
            ENTER: '\r',
            UNDO: '\x1f',
            STASH: '\x13',
            TAB: '\t',
            SHIFT_TAB: '\x1b[Z'
        };
    }

    sendKey(keyName) {
        if (!window.TerminalController) {
            console.error('DPad: TerminalController not found');
            return;
        }

        const keyCode = this.keys[keyName];

        if (!keyCode) {
            console.error('DPad: Unknown key:', keyName);
            return;
        }

        console.log('DPad: Sending key:', keyName);
        window.TerminalController.sendKeyToTerminal(keyCode);
    }
}

window.DPad = new DPad();
