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

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f"{self.base_path}{path}"
        async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
            response = await client.request(method, url, headers=self._headers(), **kwargs)
            response.raise_for_status()
            data = response.json()
            if not data.get("result", True):
                errors = data.get("messages", {}).get("error", [])
                raise RuntimeError("; ".join(errors) if errors else "MikoPBX API error")
            return data

    async def check_auth(self) -> bool:
        await self._request("GET", "/system:checkAuth")
        return True

    async def get_employees_page(self, limit: int = 100, offset: int = 0, search: str = "") -> dict[str, Any]:
        params = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        return await self._request("GET", "/employees", params=params)

    async def get_all_employees(self) -> list[dict[str, Any]]:
        employees: list[dict[str, Any]] = []
        offset = 0
        limit = 100
        while True:
            data = await self.get_employees_page(limit=limit, offset=offset)
            page_items = data.get("data", {}).get("data", [])
            employees.extend(page_items)
            if len(page_items) < limit:
                break
            offset += limit
        return employees

    async def get_extensions_for_select(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/extensions:getForSelect")
        return data.get("data", [])

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
        return await self._request("GET", "/cdr", params=params)

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
