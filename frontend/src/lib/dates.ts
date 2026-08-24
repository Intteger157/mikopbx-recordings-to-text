import { format, subDays } from "date-fns";

export function defaultFromDate(): string {
  return format(subDays(new Date(), 30), "yyyy-MM-dd");
}

export function defaultToDate(): string {
  return format(new Date(), "yyyy-MM-dd");
}

export function dateToApiStart(date: string): string {
  return new Date(`${date}T00:00:00`).toISOString();
}

export function dateToApiEnd(date: string): string {
  return new Date(`${date}T23:59:59`).toISOString();
}
