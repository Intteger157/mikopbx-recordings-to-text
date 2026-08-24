import axios from "axios";

export function getApiError(error: unknown, fallback: string): string {
  if (!axios.isAxiosError(error)) {
    return fallback;
  }

  const detail = error.response?.data?.detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item)))
      .join("; ");
  }

  const message = error.response?.data?.message;
  if (typeof message === "string") {
    return message;
  }

  if (error.message) {
    return error.message;
  }

  return fallback;
}
