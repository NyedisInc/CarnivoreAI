export function bootStep(name: string, step: () => unknown): void {
  const report = (error: unknown): void => {
    console.error(`boot step failed: ${name}`, error);
  };
  try {
    const result = step();
    if (result instanceof Promise) result.catch(report);
  } catch (error) {
    report(error);
  }
}
