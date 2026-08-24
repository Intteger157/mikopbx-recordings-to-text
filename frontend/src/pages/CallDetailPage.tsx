import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { format } from "date-fns";
import { ArrowLeft, LoaderCircle, Mic } from "lucide-react";
import api, { type CallRecordDetail, type Transcription } from "@/lib/api";
import { getApiError } from "@/lib/errors";
import { formatDuration, formatTimestamp, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TranscriptionBadge } from "@/components/TranscriptionBadge";
import { useAuthenticatedAudio } from "@/hooks/use-authenticated-audio";

export function CallDetailPage() {
  const { id } = useParams();
  const callId = Number(id);
  const queryClient = useQueryClient();
  const audioRef = useRef<HTMLAudioElement>(null);
  const [currentTime, setCurrentTime] = useState(0);

  const { data: workerStatus } = useQuery({
    queryKey: ["worker-status"],
    queryFn: async () => (await api.get<{ online: boolean; workers: string[] }>("/calls/worker-status")).data,
    refetchInterval: 10_000,
  });

  const { data: call, isLoading, isError, error } = useQuery({
    queryKey: ["call", callId],
    queryFn: async () => (await api.get<CallRecordDetail>(`/calls/${callId}`)).data,
    enabled: Number.isFinite(callId),
  });

  const { objectUrl: audioSrc, loading: audioLoading, error: audioError } = useAuthenticatedAudio(
    call?.has_audio ? `/calls/${call.id}/audio` : undefined
  );

  const { data: transcription } = useQuery({
    queryKey: ["transcription", callId],
    queryFn: async () => {
      try {
        return (await api.get<Transcription>(`/calls/${callId}/transcription`)).data;
      } catch {
        return null;
      }
    },
    enabled: Number.isFinite(callId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "PENDING" || status === "PROCESSING" ? 3000 : false;
    },
  });

  const diagnoseMutation = useMutation({
    mutationFn: async () => (await api.get(`/calls/${callId}/audio-debug`, { timeout: 120_000 })).data,
  });

  const transcribeMutation = useMutation({
    mutationFn: async () => (await api.post(`/calls/${callId}/transcribe`)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["call", callId] });
      void queryClient.invalidateQueries({ queryKey: ["transcription", callId] });
    },
  });

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTimeUpdate = () => setCurrentTime(audio.currentTime);
    audio.addEventListener("timeupdate", onTimeUpdate);
    return () => audio.removeEventListener("timeupdate", onTimeUpdate);
  }, [call?.has_audio]);

  const seek = (time: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = time;
    void audio.play();
  };

  if (!Number.isFinite(callId)) {
    return <p className="text-destructive">Invalid call ID.</p>;
  }

  if (isLoading) {
    return <div className="text-muted-foreground">Loading call details...</div>;
  }

  if (isError || !call) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">{getApiError(error, "Call not found")}</p>
        <Button asChild variant="outline">
          <Link to="/calls">Back to Call Records</Link>
        </Button>
      </div>
    );
  }

  const activeTranscription = transcription ?? call.transcription;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button asChild variant="ghost" size="icon">
          <Link to="/calls">
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Call Detail</h1>
          <p className="text-muted-foreground">{format(new Date(call.call_date), "PPpp")}</p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>Metadata</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div><span className="text-muted-foreground">From:</span> {call.src_num ?? "-"}</div>
            <div><span className="text-muted-foreground">To:</span> {call.dst_num ?? "-"}</div>
            <div><span className="text-muted-foreground">Duration:</span> {formatDuration(call.billsec || call.duration)}</div>
            <div><span className="text-muted-foreground">User:</span> {call.miko_user_name ?? "-"}</div>
            <div><span className="text-muted-foreground">Disposition:</span> {call.disposition ?? "-"}</div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Transcription:</span>
              <TranscriptionBadge status={activeTranscription?.status ?? call.transcription_status} />
            </div>
            <Button
              className="w-full"
              disabled={!call.has_audio || transcribeMutation.isPending || activeTranscription?.status === "PROCESSING"}
              onClick={() => transcribeMutation.mutate()}
            >
              {activeTranscription?.status === "PROCESSING" ? (
                <>
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  Processing...
                </>
              ) : activeTranscription?.status === "PENDING" ? (
                <>
                  <Mic className="h-4 w-4" />
                  Re-queue transcription
                </>
              ) : (
                <>
                  <Mic className="h-4 w-4" />
                  Transcribe
                </>
              )}
            </Button>
            {activeTranscription?.status === "PENDING" && (
              <p className="text-xs text-muted-foreground">
                {workerStatus?.online ? (
                  "Worker is online — transcription should start shortly."
                ) : (
                  <>
                    Celery worker is <span className="text-destructive">offline</span>. On the server:{" "}
                    <code className="rounded bg-muted px-1">docker compose up -d celery-worker</code>
                  </>
                )}
              </p>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Recording & Transcript</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {audioLoading && <p className="text-sm text-muted-foreground">Loading audio...</p>}
            {audioError && <p className="text-sm text-destructive">{audioError}</p>}

            {(audioError || (!audioLoading && !audioSrc)) && (
              <div className="space-y-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => diagnoseMutation.mutate()}
                  disabled={diagnoseMutation.isPending}
                >
                  {diagnoseMutation.isPending ? "Checking MikoPBX..." : "Diagnose recording download"}
                </Button>
                {diagnoseMutation.data && (
                  <pre className="max-h-72 overflow-auto rounded-lg border bg-muted/30 p-3 text-xs">
                    {JSON.stringify(diagnoseMutation.data, null, 2)}
                  </pre>
                )}
                {diagnoseMutation.isError && (
                  <p className="text-sm text-destructive">
                    {getApiError(diagnoseMutation.error, "Diagnostics failed")}
                  </p>
                )}
              </div>
            )}
            {audioSrc ? (
              <audio ref={audioRef} controls className="w-full" src={audioSrc} preload="metadata" />
            ) : !audioLoading ? (
              <p className="text-sm text-muted-foreground">No audio available for this call.</p>
            ) : null}

            {activeTranscription?.status === "FAILED" && (
              <p className="text-sm text-destructive">{activeTranscription.error_message}</p>
            )}

            {activeTranscription?.text && (
              <div className="rounded-lg border bg-muted/30 p-4 text-sm leading-relaxed">
                {activeTranscription.text}
              </div>
            )}

            {activeTranscription?.segments_json?.length ? (
              <div className="max-h-96 space-y-2 overflow-y-auto rounded-lg border p-4">
                {activeTranscription.segments_json.map((segment, index) => {
                  const active = currentTime >= segment.start && currentTime <= segment.end;
                  return (
                    <button
                      key={`${segment.start}-${index}`}
                      type="button"
                      onClick={() => seek(segment.start)}
                      className={cn(
                        "block w-full rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-muted",
                        active && "bg-primary/10 text-primary"
                      )}
                    >
                      <span className="mr-2 font-mono text-xs text-muted-foreground">
                        {formatTimestamp(segment.start)} - {formatTimestamp(segment.end)}
                      </span>
                      {segment.text}
                    </button>
                  );
                })}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
