import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { CheckCircle2, RefreshCw } from "lucide-react";
import { useState } from "react";
import api, { type PBXConfig } from "@/lib/api";
import { dateToApiEnd, dateToApiStart, defaultFromDate, defaultToDate } from "@/lib/dates";
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

  const { data: config } = useQuery({
    queryKey: ["pbx-config"],
    queryFn: async () => {
      const response = await api.get<PBXConfig>("/admin/pbx-config");
      setApiUrl(response.data.api_url ?? "");
      return response.data;
    },
  });

  const saveMutation = useMutation({
    mutationFn: async () =>
      (
        await api.put("/admin/pbx-config", {
          api_url: apiUrl,
          ...(apiKey ? { api_key: apiKey } : {}),
        })
      ).data,
    onSuccess: () => {
      setMessage("Configuration saved");
      void queryClient.invalidateQueries({ queryKey: ["pbx-config"] });
    },
  });

  const testMutation = useMutation({
    mutationFn: async () => (await api.post("/admin/pbx-config/test")).data,
    onSuccess: (data: { message: string }) => {
      setMessage(data.message);
      void queryClient.invalidateQueries({ queryKey: ["pbx-config"] });
    },
    onError: (error: { response?: { data?: { detail?: string } } }) => {
      setMessage(error.response?.data?.detail ?? "Connection failed");
    },
  });

  const syncMutation = useMutation({
    mutationFn: async () =>
      (
        await api.post("/admin/pbx-config/sync", {
          date_from: dateToApiStart(dateFrom),
          date_to: dateToApiEnd(dateTo),
        })
      ).data,
    onSuccess: (data: { extensions_synced: number; calls_synced: number; calls_skipped: number }) => {
      setMessage(
        `Synced ${data.extensions_synced} extensions and ${data.calls_synced} calls with recordings (${data.calls_skipped} skipped without recording).`
      );
      void queryClient.invalidateQueries({ queryKey: ["pbx-config"] });
      void queryClient.invalidateQueries({ queryKey: ["calls"] });
    },
    onError: (error: { response?: { data?: { detail?: string } } }) => {
      setMessage(error.response?.data?.detail ?? "Sync failed");
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
            Imports employees/extensions and call recordings for the selected period. Only calls with audio recordings
            are saved.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-3">
          <div className="space-y-2">
            <Label htmlFor="syncFrom">From</Label>
            <Input id="syncFrom" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="syncTo">To</Label>
            <Input id="syncTo" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </div>
          <div className="flex items-end">
            <Button className="w-full" onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending}>
              <RefreshCw className={`h-4 w-4 ${syncMutation.isPending ? "animate-spin" : ""}`} />
              Sync now
            </Button>
          </div>
        </CardContent>
      </Card>

      {message && <p className="text-sm text-muted-foreground">{message}</p>}
    </div>
  );
}
