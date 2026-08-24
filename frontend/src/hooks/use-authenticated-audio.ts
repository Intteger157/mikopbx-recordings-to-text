import { useEffect, useState } from "react";
import api from "@/lib/api";

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
      } catch {
        if (active) {
          setError("Failed to load audio");
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
