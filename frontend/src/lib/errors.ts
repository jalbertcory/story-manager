export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
export function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}
export function displayValue(value: unknown): string | number | null {
  return typeof value === "string" || typeof value === "number" ? value : null;
}
