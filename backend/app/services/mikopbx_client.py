from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx


class MikoPBXClient:
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.base_path = f"{self.api_url}/pbxcore/api/v3"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, timeout: float = 120.0, **kwargs) -> dict[str, Any]:
        url = f"{self.base_path}{path}"
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                response = await client.request(method, url, headers=self._headers(), **kwargs)
                response.raise_for_status()
                try:
                    data = response.json()
                except ValueError as exc:
                    raise RuntimeError(f"MikoPBX returned non-JSON response ({response.status_code})") from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            raise RuntimeError(f"MikoPBX HTTP {exc.response.status_code}: {body}") from exc
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
        await self._request("GET", "/system:checkAuth", timeout=30.0)
        return True

    async def get_employees_page(self, limit: int = 100, offset: int = 0, search: str = "") -> dict[str, Any]:
        params = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        return await self._request("GET", "/employees", params=params, timeout=60.0)

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
        data = await self._request("GET", "/extensions:getForSelect", timeout=60.0)
        items = data.get("data")
        return items if isinstance(items, list) else []

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

        pagination = None
        if isinstance(data, dict):
            pagination = data.get("pagination")
        if pagination is None:
            pagination = payload.get("pagination")

        if isinstance(pagination, dict):
            has_more = bool(pagination.get("hasMore"))
        else:
            has_more = len(legs) >= limit

        return legs, has_more

    async def get_cdr_page(
        self,
        date_from: datetime,
        date_to: datetime,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        params = {
            "dateFrom": date_from.strftime("%Y-%m-%dT%H:%M:%S"),
            "dateTo": date_to.strftime("%Y-%m-%dT%H:%M:%S"),
            "offset": offset,
            "limit": limit,
        }
        return await self._request("GET", "/cdr", params=params, timeout=300.0)

    def resolve_audio_url(self, audio_path: str) -> str:
        if audio_path.startswith("http"):
            return audio_path
        if audio_path.startswith("/"):
            return f"{self.api_url}{audio_path}"
        return f"{self.base_path}/{audio_path.lstrip('/')}"

    async def stream_audio(self, audio_path: str):
        url = self.resolve_audio_url(audio_path)
        client = httpx.AsyncClient(timeout=120.0, verify=False)
        request = client.build_request("GET", url, headers=self._headers())
        response = await client.send(request, stream=True)
        response.raise_for_status()
        return client, response
