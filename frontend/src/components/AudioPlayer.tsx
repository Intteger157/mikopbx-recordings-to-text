import { useEffect, useRef, useState } from "react";
import { formatTimestamp } from "@/lib/utils";
import type { TranscriptionSegment } from "@/lib/api";
import { cn } from "@/lib/utils";

interface AudioPlayerProps {
  src: string;
}

export function AudioPlayer({ src }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [currentTime, setCurrentTime] = useState(0);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTimeUpdate = () => setCurrentTime(audio.currentTime);
    audio.addEventListener("timeupdate", onTimeUpdate);
    return () => audio.removeEventListener("timeupdate", onTimeUpdate);
  }, []);

  const seek = (time: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = time;
    void audio.play();
  };

  return (
    <div className="space-y-3 rounded-xl border bg-card p-4">
      <audio ref={audioRef} controls className="w-full" src={src} preload="metadata" />
      <p className="text-sm text-muted-foreground">Current position: {formatTimestamp(currentTime)}</p>
      <TranscriptViewer segments={[]} onSeek={seek} currentTime={currentTime} placeholder />
    </div>
  );
}

interface TranscriptViewerProps {
  segments: TranscriptionSegment[];
  onSeek: (time: number) => void;
  currentTime: number;
  placeholder?: boolean;
}

export function TranscriptViewer({ segments, onSeek, currentTime, placeholder }: TranscriptViewerProps) {
  if (placeholder) {
    return null;
  }

  if (!segments.length) {
    return <p className="text-sm text-muted-foreground">No transcript segments available.</p>;
  }

  return (
    <div className="max-h-96 space-y-2 overflow-y-auto rounded-lg border p-4">
      {segments.map((segment, index) => {
        const active = currentTime >= segment.start && currentTime <= segment.end;
        return (
          <button
            key={`${segment.start}-${index}`}
            type="button"
            onClick={() => onSeek(segment.start)}
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
  );
}
