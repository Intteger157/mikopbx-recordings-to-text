from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx


class MikoPBXClient:
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

    def resolve_audio_url(self, audio_path: str) -> str:
        if audio_path.startswith("http"):
            return audio_path
        if audio_path.startswith("/"):
            return f"{self.api_url}{audio_path}"
        return f"{self.base_path}/{audio_path.lstrip('/')}"

    @staticmethod
    def extract_recording_token(audio_path: str) -> str | None:
        parsed = urlparse(audio_path if "://" in audio_path else f"https://x{audio_path}")
        tokens = parse_qs(parsed.query).get("token")
        return tokens[0] if tokens else None

    def build_recording_download_urls(self, audio_path: str, recordingfile: str | None = None) -> list[str]:
        """Build candidate download URLs per MikoPBX API docs."""
        candidates: list[str] = []
        token = self.extract_recording_token(audio_path)
        fmt = None
        if recordingfile:
            suffix = recordingfile.rsplit(".", 1)[-1].lower()
            if suffix in {"mp3", "wav", "webm", "ogg"}:
                fmt = suffix

        if token:
            params: dict[str, str] = {"token": token}
            if fmt:
                params["format"] = fmt
            query = urlencode(params)
            candidates.append(f"{self.base_path}/cdr/download?{query}")
            candidates.append(f"{self.base_path}/cdr/playback?{query}")

        candidates.append(self.resolve_audio_url(audio_path))

        unique: list[str] = []
        seen: set[str] = set()
        for url in candidates:
            if url not in seen:
                seen.add(url)
                unique.append(url)
        return unique

    @staticmethod
    def _looks_like_audio(content_type: str | None, data: bytes) -> bool:
        if len(data) < 128:
            return False
        if content_type:
            lowered = content_type.lower()
            if "json" in lowered or "text/html" in lowered:
                return False
            if lowered.startswith("audio/") or "octet-stream" in lowered:
                return True
        if data[:1] == b"{" or data[:1] == b"<":
            return False
        return True

    async def fetch_recording_bytes(
        self,
        audio_path: str,
        recordingfile: str | None = None,
    ) -> tuple[bytes, str | None]:
        urls = self.build_recording_download_urls(audio_path, recordingfile)
        timeout = httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=15.0)
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            for url in urls:
                for headers in ({}, self._headers()):
                    try:
                        response = await client.get(url, headers=headers)
                        if response.status_code >= 400:
                            errors.append(f"{url} -> HTTP {response.status_code}")
                            continue
                        content_type = response.headers.get("content-type")
                        data = response.content
                        if not self._looks_like_audio(content_type, data):
                            snippet = data[:200].decode("utf-8", errors="replace")
                            errors.append(f"{url} -> not audio ({content_type}): {snippet}")
                            continue
                        return data, content_type
                    except httpx.HTTPError as exc:
                        errors.append(f"{url} -> {exc}")

        detail = "; ".join(errors[-3:]) if errors else "no URLs tried"
        raise RuntimeError(f"Cannot download recording from MikoPBX: {detail}")

    async def stream_audio(self, audio_path: str):
        url = self.resolve_audio_url(audio_path)
        timeout = httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=15.0)
        client = httpx.AsyncClient(timeout=timeout, verify=False)
        request = client.build_request("GET", url, headers=self._headers())
        response = await client.send(request, stream=True)
        if response.status_code >= 400 and "token=" in url:
            await response.aclose()
            await client.aclose()
            client = httpx.AsyncClient(timeout=timeout, verify=False)
            request = client.build_request("GET", url)
            response = await client.send(request, stream=True)
        response.raise_for_status()
        return client, response
