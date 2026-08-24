import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { format } from "date-fns";
import { Headphones, Search } from "lucide-react";
import { useEffect, useState } from "react";
import api, { type PaginatedCalls } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateToApiEnd, dateToApiStart, defaultFromDate, defaultToDate } from "@/lib/dates";
import { formatDuration } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TranscriptionBadge } from "@/components/TranscriptionBadge";
import { Badge } from "@/components/ui/badge";

export function CallsPage() {
  const { user } = useAuth();
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [dateFrom, setDateFrom] = useState(defaultFromDate);
  const [dateTo, setDateTo] = useState(defaultToDate);

  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 400);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["calls", page, search, dateFrom, dateTo],
    queryFn: async () => {
      const response = await api.get<PaginatedCalls>("/calls", {
        params: {
          page,
          page_size: 50,
          search: search || undefined,
          date_from: dateFrom ? dateToApiStart(dateFrom) : undefined,
          date_to: dateTo ? dateToApiEnd(dateTo) : undefined,
        },
      });
      return response.data;
    },
  });

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  const resetFilters = () => {
    setSearchInput("");
    setSearch("");
    setDateFrom(defaultFromDate());
    setDateTo(defaultToDate());
    setPage(1);
  };

  const emptyMessage =
    user?.role === "USER" || user?.role === "MANAGER"
      ? "No call records for your extensions in this period. Check sync date range or assigned extensions."
      : "No call records in this period. Run Sync CDR in PBX Settings for the same date range.";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Call Records</h1>
          <p className="text-muted-foreground">
            Recordings from the last 30 days
            {user?.role !== "SUPERADMIN" && user?.allowed_extensions.length
              ? ` · extensions: ${user.allowed_extensions.join(", ")}`
              : ""}
          </p>
        </div>
        <Button variant="outline" onClick={() => setShowFilters((v) => !v)}>
          <Search className="h-4 w-4" />
          {showFilters ? "Hide filters" : "Filters"}
        </Button>
      </div>

      {showFilters && (
        <Card>
          <CardHeader>
            <CardTitle>Filters</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-5">
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="search">Phone / extension / name</Label>
              <Input
                id="search"
                placeholder="e.g. 48273190 or +7900..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="dateFrom">From</Label>
              <Input
                id="dateFrom"
                type="date"
                value={dateFrom}
                onChange={(e) => {
                  setDateFrom(e.target.value);
                  setPage(1);
                }}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="dateTo">To</Label>
              <Input
                id="dateTo"
                type="date"
                value={dateTo}
                onChange={(e) => {
                  setDateTo(e.target.value);
                  setPage(1);
                }}
              />
            </div>
            <div className="flex items-end">
              <Button variant="secondary" className="w-full" onClick={resetFilters}>
                Reset
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-8 text-center text-muted-foreground">Loading call records...</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>From</TableHead>
                  <TableHead>To</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Employee</TableHead>
                  <TableHead>Recording</TableHead>
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
                    <TableCell>{call.employee_name ?? call.miko_user_name ?? "-"}</TableCell>
                    <TableCell>
                      {call.has_audio ? (
                        <Badge variant="success" className="gap-1">
                          <Headphones className="h-3 w-3" />
                          Audio
                        </Badge>
                      ) : (
                        <Badge variant="secondary">No audio</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <TranscriptionBadge status={call.transcription_status} />
                    </TableCell>
                  </TableRow>
                ))}
                {!data?.items.length && (
                  <TableRow>
                    <TableCell colSpan={7} className="p-8 text-center text-muted-foreground">
                      {emptyMessage}
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
          {isFetching && !isLoading ? " · updating..." : ""}
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
