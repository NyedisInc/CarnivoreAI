export function twoFrames(limitMs = 250): Promise<void> {
  const frames = new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  const timer = new Promise<void>((resolve) => setTimeout(resolve, limitMs));
  return Promise.race([frames, timer]);
}
