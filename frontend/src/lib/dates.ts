export function defaultFromDate(): string {
  const date = new Date();
  date.setDate(date.getDate() - 30);
  return formatLocalDate(date);
}

export function defaultToDate(): string {
  return formatLocalDate(new Date());
}

function formatLocalDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** MikoPBX expects local datetime without timezone suffix */
export function dateToApiStart(date: string): string {
  return `${date}T00:00:00`;
}

export function dateToApiEnd(date: string): string {
  return `${date}T23:59:59`;
}
