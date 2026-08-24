import { useEffect, useState } from "react";
import api from "@/lib/api";

/** Blob responses keep the error envelope unparsed, so read it manually. */
async function extractErrorDetail(error: unknown): Promise<string> {
  const data = (error as { response?: { data?: unknown } })?.response?.data;

  if (data instanceof Blob) {
    try {
      const text = await data.text();
      const parsed = JSON.parse(text) as { detail?: string };
      if (parsed.detail) return parsed.detail;
      if (text) return text;
    } catch {
      // fall through to generic message
    }
  }

  if (typeof data === "object" && data !== null && "detail" in data) {
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }

  if (error instanceof Error && error.message) return error.message;
  return "Failed to load audio";
}

export function useAuthenticatedAudio(url: string | undefined) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!url) {
      setObjectUrl(null);
      return;
    }

    let active = true;
    let createdUrl: string | null = null;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await api.get(url, { responseType: "blob", timeout: 180_000 });
        if (!active) return;
        createdUrl = URL.createObjectURL(response.data);
        setObjectUrl(createdUrl);
      } catch (err) {
        const detail = await extractErrorDetail(err);
        if (active) {
          setError(detail);
          setObjectUrl(null);
        }
      } finally {
        if (active) setLoading(false);
      }
    };

    void load();

    return () => {
      active = false;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [url]);

  return { objectUrl, loading, error };
}
