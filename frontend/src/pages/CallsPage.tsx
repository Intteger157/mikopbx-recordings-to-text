import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { format } from "date-fns";
import api, { type PaginatedCalls } from "@/lib/api";
import { formatDuration } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TranscriptionBadge } from "@/components/TranscriptionBadge";
import { useState } from "react";

export function CallsPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["calls", page, search, dateFrom, dateTo],
    queryFn: async () => {
      const response = await api.get<PaginatedCalls>("/calls", {
        params: {
          page,
          page_size: 20,
          search: search || undefined,
          date_from: dateFrom ? new Date(dateFrom).toISOString() : undefined,
          date_to: dateTo ? new Date(dateTo).toISOString() : undefined,
        },
      });
      return response.data;
    },
  });

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Call Records</h1>
        <p className="text-muted-foreground">Browse synced MikoPBX recordings and transcription status.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-4">
          <div className="space-y-2">
            <Label htmlFor="search">Search</Label>
            <Input id="search" placeholder="Extension, user, uniqueid" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="dateFrom">From</Label>
            <Input id="dateFrom" type="datetime-local" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="dateTo">To</Label>
            <Input id="dateTo" type="datetime-local" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </div>
          <div className="flex items-end">
            <Button variant="secondary" onClick={() => setPage(1)}>
              Apply
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-8 text-center text-muted-foreground">Loading calls...</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>From</TableHead>
                  <TableHead>To</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>User</TableHead>
                  <TableHead>Transcription</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.items.map((call) => (
                  <TableRow key={call.id}>
                    <TableCell>
                      <Link to={`/calls/${call.id}`} className="font-medium text-primary hover:underline">
                        {format(new Date(call.call_date), "yyyy-MM-dd HH:mm")}
                      </Link>
                    </TableCell>
                    <TableCell>{call.src_num ?? "-"}</TableCell>
                    <TableCell>{call.dst_num ?? "-"}</TableCell>
                    <TableCell>{formatDuration(call.billsec || call.duration)}</TableCell>
                    <TableCell>{call.miko_user_name ?? "-"}</TableCell>
                    <TableCell>
                      <TranscriptionBadge status={call.transcription_status} />
                    </TableCell>
                  </TableRow>
                ))}
                {!data?.items.length && (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-muted-foreground">
                      No call records found. Configure MikoPBX and run a sync.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Page {page} of {totalPages} · {data?.total ?? 0} total
        </p>
        <div className="flex gap-2">
          <Button variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <Button variant="outline" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
