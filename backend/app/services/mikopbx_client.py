from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

logger = logging.getLogger(__name__)


class MikoPBXClient:
    MIN_RECORDING_BYTES = 2048
    RESUME_CHUNK_BYTES = 16 * 1024
    MAX_RESUME_CHUNK_BYTES = 1024 * 1024
    RESUME_READ_TIMEOUT = 20.0
    MAX_RESUME_STALLS = 3
    MAX_RESUME_REQUESTS = 800
    _TOKEN_IN_URL = re.compile(r"token=([a-f0-9]{32,64})", re.IGNORECASE)

    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.base_path = f"{self.api_url}/pbxcore/api/v3"
        self._default_timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)
        self._cdr_timeout = httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=15.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        timeout: httpx.Timeout | float | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        url = f"{self.base_path}{path}"
        request_timeout = self._default_timeout if timeout is None else timeout
        try:
            async with httpx.AsyncClient(timeout=request_timeout, verify=False) as client:
                response = await client.request(method, url, headers=self._headers(), **kwargs)
                response.raise_for_status()
                try:
                    data = response.json()
                except ValueError as exc:
                    raise RuntimeError(f"MikoPBX returned non-JSON response ({response.status_code})") from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            raise RuntimeError(f"MikoPBX HTTP {exc.response.status_code}: {body}") from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"MikoPBX request timed out ({path}): {exc}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Cannot reach MikoPBX at {self.api_url}: {exc}") from exc

        if not data.get("result", True):
            errors = data.get("messages", {}).get("error", [])
            if isinstance(errors, list):
                message = "; ".join(str(item) for item in errors if item)
            else:
                message = str(errors)
            raise RuntimeError(message or "MikoPBX API error")
        return data

    @staticmethod
    def _extract_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            inner = data.get("data")
            if isinstance(inner, list):
                return inner
            records = data.get("records")
            if isinstance(records, list):
                return records
        return []

    async def check_auth(self) -> bool:
        await self._request("GET", "/system:checkAuth", timeout=httpx.Timeout(30.0))
        return True

    async def get_employees_page(self, limit: int = 100, offset: int = 0, search: str = "") -> dict[str, Any]:
        params = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        return await self._request("GET", "/employees", params=params, timeout=httpx.Timeout(60.0))

    async def get_all_employees(self) -> list[dict[str, Any]]:
        employees: list[dict[str, Any]] = []
        offset = 0
        limit = 100
        while True:
            data = await self.get_employees_page(limit=limit, offset=offset)
            page_items = self._extract_list(data)
            if not page_items:
                break
            employees.extend(page_items)
            if len(page_items) < limit:
                break
            offset += limit
        return employees

    async def get_extensions_for_select(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/extensions:getForSelect", timeout=httpx.Timeout(60.0))
        items = data.get("data")
        return items if isinstance(items, list) else []

    @staticmethod
    def _extract_pagination(payload: dict[str, Any]) -> dict[str, Any] | None:
        data = payload.get("data")
        pagination = data.get("pagination") if isinstance(data, dict) else None
        if pagination is None:
            pagination = payload.get("pagination")
        return pagination if isinstance(pagination, dict) else None

    @staticmethod
    def parse_cdr_page(payload: dict[str, Any], limit: int) -> tuple[list[dict[str, Any]], bool]:
        """Parse MikoPBX CDR response.

        Supports:
        - flat array in ``data`` (documented format)
        - grouped ``data.records[]`` with nested ``records[]`` legs
        """
        data = payload.get("data")
        legs: list[dict[str, Any]] = []

        if isinstance(data, list):
            legs = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            records = data.get("records", [])
            if not isinstance(records, list):
                records = []

            for item in records:
                if not isinstance(item, dict):
                    continue
                inner = item.get("records")
                if isinstance(inner, list) and inner:
                    for leg in inner:
                        if isinstance(leg, dict):
                            legs.append(
                                {
                                    **leg,
                                    "_group_start": item.get("start"),
                                    "_group_src": item.get("src_num"),
                                    "_group_dst": item.get("dst_num"),
                                    "_group_linkedid": item.get("linkedid"),
                                    "_group_src_name": item.get("src_name"),
                                    "_group_dst_name": item.get("dst_name"),
                                    "_group_disposition": item.get("disposition"),
                                    "_group_duration": item.get("totalDuration"),
                                    "_group_billsec": item.get("totalBillsec"),
                                }
                            )
                else:
                    legs.append(item)

        pagination = MikoPBXClient._extract_pagination(payload)

        if isinstance(pagination, dict):
            has_more = bool(pagination.get("hasMore"))
        else:
            has_more = len(legs) >= limit

        return legs, has_more, pagination

    async def get_cdr_record(self, cdr_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/cdr/{cdr_id}", timeout=httpx.Timeout(60.0))

    @classmethod
    def find_recording_url(cls, payload: Any, cdr_id: int | None = None) -> str | None:
        """Search a CDR payload for a recording URL.

        Legs can sit at the top level or nested under ``records``, and missing
        the nested case means falling back to a stale token that MikoPBX
        rejects with "Invalid or expired playback token".
        """

        def walk(node: Any, want_id: bool) -> str | None:
            if isinstance(node, dict):
                url = node.get("download_url") or node.get("playback_url")
                if url:
                    if not want_id:
                        return url
                    if cdr_id is not None and str(node.get("id")) == str(cdr_id):
                        return url
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        found = walk(value, want_id)
                        if found:
                            return found
            elif isinstance(node, list):
                for item in node:
                    found = walk(item, want_id)
                    if found:
                        return found
            return None

        if cdr_id is not None:
            exact = walk(payload, True)
            if exact:
                return exact
        return walk(payload, False)

    async def get_cdr_recording_url(self, cdr_id: int) -> str | None:
        payload = await self.get_cdr_record(cdr_id)
        return self.find_recording_url(payload, cdr_id)

    async def get_cdr_page(
        self,
        date_from: datetime,
        date_to: datetime,
        offset: int = 0,
        limit: int = 50,
        last_id: int | None = None,
        src_num: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "dateFrom": date_from.strftime("%Y-%m-%dT%H:%M:%S"),
            "dateTo": date_to.strftime("%Y-%m-%dT%H:%M:%S"),
            "offset": offset,
            "limit": limit,
            "disposition": "ANSWERED",
        }
        if last_id is not None:
            params["lastId"] = last_id
        if src_num:
            params["src_num"] = src_num
        return await self._request("GET", "/cdr", params=params, timeout=self._cdr_timeout)

    def _recording_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "*/*",
            # Audio is already compressed; gzip only adds buffering on the PBX side.
            "Accept-Encoding": "identity",
        }

    def resolve_audio_url(self, audio_path: str) -> str:
        if audio_path.startswith("http"):
            return audio_path
        if audio_path.startswith("/"):
            return f"{self.api_url}{audio_path}"
        return f"{self.base_path}/{audio_path.lstrip('/')}"

    @classmethod
    def clean_recording_token(cls, raw: str) -> str:
        """MikoPBX sometimes glues ``format=webm`` onto the token without ``&``."""
        token = raw.strip()
        lower = token.lower()
        for marker in ("format=", "view=", "&"):
            idx = lower.find(marker)
            if idx > 0:
                token = token[:idx]
                lower = token.lower()
        return token

    @classmethod
    def extract_recording_token(cls, audio_path: str) -> str | None:
        if not audio_path:
            return None

        parsed = urlparse(audio_path if "://" in audio_path else f"https://x{audio_path}")
        tokens = parse_qs(parsed.query).get("token")
        if tokens and tokens[0]:
            return cls.clean_recording_token(tokens[0])

        match = cls._TOKEN_IN_URL.search(audio_path)
        return cls.clean_recording_token(match.group(1)) if match else None

    @staticmethod
    def _recording_format(recordingfile: str | None) -> str | None:
        if not recordingfile:
            return None
        suffix = recordingfile.rsplit(".", 1)[-1].lower()
        return suffix if suffix in {"mp3", "wav", "webm", "ogg"} else None

    def build_recording_download_url(
        self,
        token: str,
        recordingfile: str | None = None,
        cdr_id: int | None = None,
    ) -> str:
        """Build the documented download URL.

        The API exposes only ``/cdr:download`` and ``/cdr:playback``; there is
        no per-id download route, and ``/cdr/download`` resolves to
        ``getRecord(id=download)`` and returns JSON.
        """
        params: dict[str, str] = {"token": self.clean_recording_token(token)}
        fmt = self._recording_format(recordingfile)
        if fmt:
            params["format"] = fmt
        return f"{self.base_path}/cdr:download?{urlencode(params)}"

    def build_recording_download_urls(
        self,
        audio_path: str,
        recordingfile: str | None = None,
        cdr_id: int | None = None,
    ) -> list[str]:
        """Return candidate download URLs, cheapest first (Bearer required)."""
        token = self.extract_recording_token(audio_path)
        if not token:
            resolved = self.resolve_audio_url(audio_path)
            return [resolved] if resolved else []

        clean = self.clean_recording_token(token)
        fmt = self._recording_format(recordingfile)

        candidates: list[str] = []
        if audio_path and ":download" in audio_path:
            candidates.append(self.resolve_audio_url(audio_path))
        candidates.append(f"{self.base_path}/cdr:download?{urlencode({'token': clean})}")
        if fmt:
            candidates.append(f"{self.base_path}/cdr:download?{urlencode({'token': clean, 'format': fmt})}")
        candidates.append(f"{self.base_path}/cdr:download?{urlencode({'token': clean, 'format': 'mp3'})}")
        candidates.append(f"{self.base_path}/cdr:playback?{urlencode({'token': clean})}")

        unique: list[str] = []
        seen: set[str] = set()
        for url in candidates:
            if url not in seen:
                seen.add(url)
                unique.append(url)
        return unique

    @staticmethod
    def _is_json_or_html(content_type: str | None, data: bytes) -> bool:
        if content_type:
            lowered = content_type.lower()
            if "json" in lowered or "html" in lowered or lowered.startswith("text/"):
                return True
        return data[:1] in {b"{", b"<", b"["}

    _RESPONSE_HEADERS_OF_INTEREST = (
        "content-type",
        "content-length",
        "content-range",
        "content-disposition",
        "transfer-encoding",
        "content-encoding",
        "accept-ranges",
        "server",
    )

    @staticmethod
    def _parse_content_range_total(value: str | None) -> int | None:
        """Read the total size out of a ``bytes 0-16383/202798`` header."""
        if not value:
            return None
        total = value.rpartition("/")[2].strip()
        return int(total) if total.isdigit() else None

    async def _read_recording_body(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        timeout: httpx.Timeout | float | None = None,
    ) -> tuple[bytes, dict[str, str], int]:
        """Stream a recording, returning the body plus the response headers.

        Headers and any bytes received so far come back even when the transfer
        stalls, so callers can resume with a Range request instead of losing
        everything to a timeout.
        """
        chunks: list[bytes] = []
        stream_kwargs = {} if timeout is None else {"timeout": timeout}
        async with client.stream("GET", url, headers=headers, **stream_kwargs) as response:
            status = response.status_code
            meta = {
                key: value
                for key, value in ((name, response.headers.get(name)) for name in self._RESPONSE_HEADERS_OF_INTEREST)
                if value
            }
            if status >= 400:
                body = await response.aread()
                return body[:2048], meta, status

            content_length = response.headers.get("content-length")
            target = int(content_length) if content_length and content_length.isdigit() else None

            total = 0
            try:
                # chunk_size=None yields whatever arrived, so a stall mid-transfer
                # still leaves us the bytes we already have.
                async for chunk in response.aiter_bytes(chunk_size=None):
                    chunks.append(chunk)
                    total += len(chunk)
                    if target is not None and total >= target:
                        break
                    if total > 100 * 1024 * 1024:
                        break
            except httpx.TimeoutException:
                if not chunks:
                    raise

        return b"".join(chunks), meta, status

    async def _download_recording(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        read_timeout: float,
    ) -> tuple[bytes, dict[str, str], int]:
        """Download one recording URL, preferring ranged chunks.

        MikoPBX throttles a single response to roughly 20 KB but answers Range
        requests instantly, so start with a small range and take the plain
        stream only when ranges are refused.
        """
        probe_timeout = httpx.Timeout(connect=10.0, read=self.RESUME_READ_TIMEOUT, write=20.0, pool=10.0)
        probe_headers = {**headers, "Range": f"bytes=0-{self.RESUME_CHUNK_BYTES - 1}"}
        data, meta, status = await self._read_recording_body(client, url, probe_headers, timeout=probe_timeout)

        if status == 206:
            total = self._parse_content_range_total(meta.get("content-range"))
            if total and len(data) < total:
                data = await self._resume_recording(client, url, headers, data, total)
            return data, {**meta, "content-length": str(total or len(data))}, 200

        if status >= 400 and status != 416:
            return data, meta, status

        stream_timeout = httpx.Timeout(connect=10.0, read=read_timeout, write=20.0, pool=10.0)
        data, meta, status = await self._read_recording_body(client, url, headers, timeout=stream_timeout)
        declared = meta.get("content-length")
        total = int(declared) if declared and declared.isdigit() else None
        if status < 400 and total and len(data) < total:
            data = await self._resume_recording(client, url, headers, data, total)
        return data, meta, status

    async def _resume_recording(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        data: bytes,
        total_size: int,
    ) -> bytes:
        """Finish a stalled download with small Range requests.

        MikoPBX advertises ``Accept-Ranges: bytes`` but stalls after roughly
        20 KB on a single connection, so ask for chunks small enough to arrive
        before the stall and stop once several requests make no progress.
        """
        timeout = httpx.Timeout(connect=10.0, read=self.RESUME_READ_TIMEOUT, write=20.0, pool=10.0)
        chunk_size = self.RESUME_CHUNK_BYTES
        may_grow = True
        stalled = 0
        requests = 0

        while len(data) < total_size and stalled < self.MAX_RESUME_STALLS:
            if requests >= self.MAX_RESUME_REQUESTS:
                logger.warning("Giving up resuming %s after %d range requests", url, requests)
                break

            start = len(data)
            end = min(start + chunk_size, total_size) - 1
            requested = end - start + 1
            range_headers = {**headers, "Range": f"bytes={start}-{end}"}
            requests += 1

            try:
                chunk, _, status = await self._read_recording_body(client, url, range_headers, timeout=timeout)
            except httpx.HTTPError:
                stalled += 1
                continue

            if status not in {200, 206} or not chunk:
                stalled += 1
                continue

            if status == 200 and len(chunk) >= total_size:
                # The server ignored Range and sent the whole file.
                return chunk

            data += chunk
            stalled = 0
            if len(chunk) < requested:
                # A short chunk means the throttle kicked in; stop probing bigger
                # sizes so we never pay another stall timeout.
                may_grow = False
                chunk_size = self.RESUME_CHUNK_BYTES
            elif may_grow:
                chunk_size = min(chunk_size * 2, self.MAX_RESUME_CHUNK_BYTES)

        if len(data) >= total_size:
            logger.info("Resumed recording download to %d bytes in %d range requests", len(data), requests)
        return data

    async def fetch_recording_bytes(
        self,
        audio_path: str,
        recordingfile: str | None = None,
        cdr_id: int | None = None,
        read_timeout: float = 60.0,
        max_urls: int | None = None,
    ) -> tuple[bytes, str | None]:
        """Download a recording, trying each candidate URL in turn.

        ``read_timeout`` is per URL: the API keeps it short so the browser does
        not hang, while the transcription worker can afford to wait.
        """
        urls = self.build_recording_download_urls(audio_path, recordingfile, cdr_id)
        if max_urls is not None:
            urls = urls[:max_urls]
        timeout = httpx.Timeout(connect=10.0, read=read_timeout, write=20.0, pool=10.0)
        errors: list[str] = []
        headers = self._recording_headers()

        async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
            for url in urls:
                try:
                    data, meta, http_status = await self._download_recording(client, url, headers, read_timeout)
                except httpx.HTTPError as exc:
                    errors.append(f"{url} -> {type(exc).__name__}")
                    continue

                content_type = meta.get("content-type")
                described = ", ".join(f"{key}={value}" for key, value in meta.items()) or "no headers"

                if http_status >= 400:
                    snippet = data[:200].decode("utf-8", errors="replace")
                    errors.append(f"{url} -> HTTP {http_status} ({described}): {snippet}")
                    continue
                if self._is_json_or_html(content_type, data):
                    snippet = data[:200].decode("utf-8", errors="replace")
                    errors.append(f"{url} -> {described}: {snippet}")
                    continue

                declared = meta.get("content-length")
                total_size = int(declared) if declared and declared.isdigit() else None
                if len(data) < self.MIN_RECORDING_BYTES:
                    errors.append(f"{url} -> only {len(data)} bytes ({described})")
                    continue
                if total_size and len(data) < total_size:
                    errors.append(f"{url} -> incomplete {len(data)}/{total_size} bytes ({described})")
                    continue

                logger.info("Recording downloaded from %s (%s, %d bytes)", url, content_type, len(data))
                return data, content_type

        for message in errors:
            logger.warning("Recording download attempt failed: %s", message)
        detail = "; ".join(errors) if errors else "no URLs tried"
        raise RuntimeError(f"Cannot download recording from MikoPBX: {detail}")

    async def probe_recording_urls(
        self,
        audio_path: str,
        recordingfile: str | None = None,
        cdr_id: int | None = None,
        read_timeout: float = 20.0,
    ) -> list[dict[str, Any]]:
        """Try every candidate recording URL and report what MikoPBX answered."""
        urls = self.build_recording_download_urls(audio_path, recordingfile, cdr_id)
        timeout = httpx.Timeout(connect=8.0, read=read_timeout, write=10.0, pool=8.0)
        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
            headers = self._recording_headers()
            # Probe with a small range so diagnostics answer fast even when the
            # PBX throttles full responses.
            probe_headers = {**headers, "Range": f"bytes=0-{self.RESUME_CHUNK_BYTES - 1}"}
            for url in urls:
                entry: dict[str, Any] = {"url": url, "auth": "bearer", "range": "bytes=0-16383"}
                try:
                    data, meta, http_status = await self._read_recording_body(client, url, probe_headers)
                    entry["status"] = http_status
                    entry["headers"] = meta
                    entry["bytes"] = len(data)
                    entry["total_bytes"] = self._parse_content_range_total(meta.get("content-range"))
                    if self._is_json_or_html(meta.get("content-type"), data) or not data:
                        entry["usable"] = False
                        entry["body"] = data[:300].decode("utf-8", errors="replace")
                    else:
                        entry["usable"] = http_status in {200, 206}
                except httpx.HTTPError as exc:
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                results.append(entry)
        return results
