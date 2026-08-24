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

    async def get_cdr_recording_url(self, cdr_id: int) -> str | None:
        payload = await self.get_cdr_record(cdr_id)
        record = payload.get("data")
        if isinstance(record, list):
            record = record[0] if record and isinstance(record[0], dict) else None
        if isinstance(record, dict):
            return record.get("download_url") or record.get("playback_url")
        return None

    async def get_cdr_page(
        self,
        date_from: datetime,
        date_to: datetime,
        offset: int = 0,
        limit: int = 50,
        last_id: int | None = None,
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
        return await self._request("GET", "/cdr", params=params, timeout=self._cdr_timeout)

    def _recording_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "*/*",
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
    ) -> str:
        params: dict[str, str] = {"token": self.clean_recording_token(token)}
        fmt = self._recording_format(recordingfile)
        if fmt:
            params["format"] = fmt
        return f"{self.base_path}/cdr/download?{urlencode(params)}"

    def build_recording_download_urls(
        self,
        audio_path: str,
        recordingfile: str | None = None,
        cdr_id: int | None = None,
    ) -> list[str]:
        """Return a short list of well-formed download URLs (Bearer required)."""
        token = self.extract_recording_token(audio_path)
        if not token:
            return [self.resolve_audio_url(audio_path)]

        primary = self.build_recording_download_url(token, recordingfile)
        candidates = [
            primary,
            f"{self.base_path}/cdr:download?{urlencode({'token': self.clean_recording_token(token)})}",
        ]
        if cdr_id is not None:
            q = urlencode({"token": self.clean_recording_token(token)})
            candidates.append(f"{self.base_path}/cdr/{cdr_id}:download?{q}")

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

    async def _read_recording_body(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
    ) -> tuple[bytes, str | None, int]:
        """Read a recording body, tolerating servers that keep the socket open.

        MikoPBX streams recordings with HTTP Range support and does not always
        close the connection, so a plain read would block until timeout. We stop
        as soon as the advertised length is reached and accept whatever arrived
        if the stream stalls afterwards.
        """
        request_headers = {**headers, "Range": "bytes=0-"}
        async with client.stream("GET", url, headers=request_headers) as response:
            status = response.status_code
            content_type = response.headers.get("content-type")
            if status >= 400:
                return b"", content_type, status

            expected = response.headers.get("content-length")
            try:
                expected_bytes = int(expected) if expected else None
            except ValueError:
                expected_bytes = None

            buffer = bytearray()
            try:
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    buffer += chunk
                    if expected_bytes is not None and len(buffer) >= expected_bytes:
                        break
                    if len(buffer) > 200 * 1024 * 1024:
                        break
            except httpx.TimeoutException:
                if len(buffer) < self.MIN_RECORDING_BYTES:
                    raise

            return bytes(buffer), content_type, status

    async def fetch_recording_bytes(
        self,
        audio_path: str,
        recordingfile: str | None = None,
        cdr_id: int | None = None,
    ) -> tuple[bytes, str | None]:
        urls = self.build_recording_download_urls(audio_path, recordingfile, cdr_id)
        timeout = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)
        errors: list[str] = []
        headers = self._recording_headers()

        async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
            for url in urls:
                try:
                    data, content_type, http_status = await self._read_recording_body(client, url, headers)
                except httpx.HTTPError as exc:
                    errors.append(f"{url} -> {type(exc).__name__}")
                    continue

                if http_status >= 400:
                    errors.append(f"{url} -> HTTP {http_status}")
                    continue
                if self._is_json_or_html(content_type, data):
                    snippet = data[:200].decode("utf-8", errors="replace")
                    errors.append(f"{url} -> {content_type}: {snippet}")
                    continue
                if len(data) < self.MIN_RECORDING_BYTES:
                    errors.append(f"{url} -> only {len(data)} bytes")
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
    ) -> list[dict[str, Any]]:
        """Try every candidate recording URL and report what MikoPBX answered."""
        urls = self.build_recording_download_urls(audio_path, recordingfile, cdr_id)
        timeout = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
            headers = self._recording_headers()
            for url in urls:
                entry: dict[str, Any] = {"url": url, "auth": "bearer"}
                try:
                    data, content_type, http_status = await self._read_recording_body(client, url, headers)
                    entry["status"] = http_status
                    entry["content_type"] = content_type
                    entry["bytes"] = len(data)
                    if self._is_json_or_html(content_type, data) or len(data) < self.MIN_RECORDING_BYTES:
                        entry["usable"] = False
                        entry["body"] = data[:300].decode("utf-8", errors="replace")
                    else:
                        entry["usable"] = True
                except httpx.HTTPError as exc:
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                results.append(entry)
        return results
