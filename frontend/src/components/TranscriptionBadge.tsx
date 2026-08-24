import type { TranscriptionStatus } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const statusConfig: Record<
  TranscriptionStatus,
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" }
> = {
  PENDING: { label: "Pending", variant: "warning" },
  PROCESSING: { label: "Processing", variant: "default" },
  COMPLETED: { label: "Completed", variant: "success" },
  FAILED: { label: "Failed", variant: "destructive" },
};

export function TranscriptionBadge({ status }: { status: TranscriptionStatus | null }) {
  if (!status) {
    return <Badge variant="secondary">Not transcribed</Badge>;
  }
  const config = statusConfig[status];
  return <Badge variant={config.variant}>{config.label}</Badge>;
}
