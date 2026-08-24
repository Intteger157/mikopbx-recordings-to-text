import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { CheckCircle2, LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import api, { type PBXConfig, type PBXSyncStatus } from "@/lib/api";
import { dateToApiEnd, dateToApiStart, defaultFromDate, defaultToDate } from "@/lib/dates";
import { getApiError } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function AdminPBXPage() {
  const queryClient = useQueryClient();
  const [apiUrl, setApiUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [dateFrom, setDateFrom] = useState(defaultFromDate);
  const [dateTo, setDateTo] = useState(defaultToDate);
  const [message, setMessage] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);

  const { data: config } = useQuery({
    queryKey: ["pbx-config"],
    queryFn: async () => {
      const response = await api.get<PBXConfig>("/admin/pbx-config");
      setApiUrl(response.data.api_url ?? "");
      return response.data;
    },
  });

  const { data: syncStatus } = useQuery({
    queryKey: ["sync-status"],
    queryFn: async () => (await api.get<PBXSyncStatus>("/admin/pbx-config/sync-status")).data,
    refetchInterval: (query) => (query.state.data?.state === "running" ? 1500 : false),
  });

  const isSyncing = syncStatus?.state === "running";

  useEffect(() => {
    if (!syncStatus) return;

    if (syncStatus.state === "completed") {
      setIsError(false);
      setMessage(
        `Synced ${syncStatus.extensions_synced} extensions and ${syncStatus.calls_synced} calls with recordings (${syncStatus.calls_skipped} skipped).`
      );
      void queryClient.invalidateQueries({ queryKey: ["pbx-config"] });
      void queryClient.invalidateQueries({ queryKey: ["calls"] });
      void queryClient.invalidateQueries({ queryKey: ["extensions"] });
    }

    if (syncStatus.state === "failed") {
      setIsError(true);
      setMessage(syncStatus.error ?? "Sync failed");
    }
  }, [syncStatus?.state, syncStatus?.finished_at]);

  const saveMutation = useMutation({
    mutationFn: async () =>
      (
        await api.put("/admin/pbx-config", {
          api_url: apiUrl,
          ...(apiKey ? { api_key: apiKey } : {}),
        })
      ).data,
    onSuccess: () => {
      setIsError(false);
      setMessage("Configuration saved");
      void queryClient.invalidateQueries({ queryKey: ["pbx-config"] });
    },
  });

  const testMutation = useMutation({
    mutationFn: async () => (await api.post("/admin/pbx-config/test")).data,
    onSuccess: (data: { message: string }) => {
      setIsError(false);
      setMessage(data.message);
      void queryClient.invalidateQueries({ queryKey: ["pbx-config"] });
    },
    onError: (error: unknown) => {
      setIsError(true);
      setMessage(getApiError(error, "Connection failed"));
    },
  });

  const cancelSyncMutation = useMutation({
    mutationFn: async () => (await api.post("/admin/pbx-config/sync/cancel")).data,
    onSuccess: () => {
      setIsError(false);
      setMessage("Sync cancelled");
      void queryClient.invalidateQueries({ queryKey: ["sync-status"] });
    },
  });

  const syncAgeSeconds =
    syncStatus?.updated_at != null
      ? Math.floor((Date.now() - new Date(syncStatus.updated_at).getTime()) / 1000)
      : null;
  const syncLooksStuck = isSyncing && syncAgeSeconds != null && syncAgeSeconds > 120;

  const syncMutation = useMutation({
    mutationFn: async () =>
      (
        await api.post("/admin/pbx-config/sync", {
          date_from: dateToApiStart(dateFrom),
          date_to: dateToApiEnd(dateTo),
        })
      ).data,
    onSuccess: () => {
      setIsError(false);
      setMessage("Sync started — importing recordings in background...");
      void queryClient.invalidateQueries({ queryKey: ["sync-status"] });
    },
    onError: (error: unknown) => {
      setIsError(true);
      setMessage(getApiError(error, "Sync failed"));
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">MikoPBX Settings</h1>
        <p className="text-muted-foreground">Configure API access and sync call detail records.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Connection</CardTitle>
          <CardDescription>
            Status: {config?.is_connected ? "Connected" : "Not connected"}
            {config?.last_sync_at && ` · Last sync ${format(new Date(config.last_sync_at), "PPpp")}`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="apiUrl">API URL</Label>
            <Input
              id="apiUrl"
              placeholder="https://pbx.example.com"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="apiKey">API Key</Label>
            <Input
              id="apiKey"
              type="password"
              placeholder={config?.has_api_key ? "•••••••• (leave blank to keep)" : "Bearer API key"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending || !apiUrl || (!apiKey && !config?.has_api_key)}
            >
              Save
            </Button>
            <Button variant="secondary" onClick={() => testMutation.mutate()} disabled={testMutation.isPending}>
              <CheckCircle2 className="h-4 w-4" />
              Test connection
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Sync CDR</CardTitle>
          <CardDescription>
            Runs in background. Recordings appear in Call Records as each page is imported. Only calls with audio
            recordings are saved.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="syncFrom">From</Label>
              <Input id="syncFrom" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="syncTo">To</Label>
              <Input id="syncTo" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
            </div>
            <div className="flex items-end gap-2">
              <Button
                className="w-full"
                onClick={() => syncMutation.mutate()}
                disabled={syncMutation.isPending || isSyncing}
              >
                {isSyncing ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                {isSyncing ? "Syncing..." : "Sync now"}
              </Button>
              {isSyncing && (
                <Button
                  variant="outline"
                  onClick={() => cancelSyncMutation.mutate()}
                  disabled={cancelSyncMutation.isPending}
                >
                  Cancel
                </Button>
              )}
            </div>
          </div>

          {isSyncing && syncStatus && (
            <div className="rounded-lg border bg-muted/30 p-4 text-sm">
              <p className="font-medium">{syncStatus.message}</p>
              <p className="mt-2 text-muted-foreground">
                Extensions: {syncStatus.extensions_synced} · Calls imported: {syncStatus.calls_synced} · Skipped:{" "}
                {syncStatus.calls_skipped}
                {syncStatus.cdr_page > 0 ? ` · CDR page ${syncStatus.cdr_page}` : ""}
              </p>
              <p className="mt-2 text-muted-foreground">
                You can open Call Records — new entries appear as sync progresses.
              </p>
              {syncLooksStuck && (
                <p className="mt-2 text-destructive">
                  No progress for over 2 minutes. MikoPBX may be slow — try a shorter date range (3–7 days) or click
                  Cancel and retry.
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {message && <p className={`text-sm ${isError ? "text-destructive" : "text-muted-foreground"}`}>{message}</p>}
    </div>
  );
}
