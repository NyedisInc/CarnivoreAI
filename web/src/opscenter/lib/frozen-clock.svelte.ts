
function pad(value: number): string {
  return String(Math.floor(value)).padStart(2, '0');
}

function frozenFromSearch(): string | null {
  if (typeof window === 'undefined' || !window.location) return null;
  const asked = new URLSearchParams(window.location.search).get('t');
  return asked && /^\d{2}:\d{2}:\d{2}$/.test(asked) ? asked : null;
}

const frozen = frozenFromSearch();

export const clock: { now: string; frozen: boolean } = $state({
  now: frozen ?? `${pad(new Date().getHours())}:${pad(new Date().getMinutes())}:${pad(new Date().getSeconds())}`,
  frozen: frozen !== null,
});

let timer: ReturnType<typeof setInterval> | undefined;
let holders = 0;

export function startClock(): () => void {
  if (clock.frozen) return () => {};
  holders += 1;
  if (timer === undefined) {
    timer = setInterval(() => {
      const now = new Date();
      clock.now = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    }, 1000);
  }
  let held = true;
  return () => {
    if (!held) return;
    held = false;
    holders -= 1;
    if (holders <= 0 && timer !== undefined) {
      clearInterval(timer);
      timer = undefined;
      holders = 0;
    }
  };
}
