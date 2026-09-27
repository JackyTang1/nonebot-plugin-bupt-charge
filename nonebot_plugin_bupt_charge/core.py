"""Platform-independent station matching, querying and formatting."""

from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Sequence

import httpx


@dataclass(frozen=True)
class Station:
    station_no: int
    campus: str
    location: str
    sn: str
    socket_count: int
    gps_id: int | None = None
    marked_new: bool = False


@dataclass(frozen=True)
class Snapshot:
    station: Station
    free_ports: tuple[int, ...]
    busy_ports: tuple[int, ...]
    faulty_ports: tuple[int, ...]


class ChargingError(Exception):
    """A query failed; never treat this as zero available sockets."""


def load_stations() -> tuple[Station, ...]:
    data_file = files("nonebot_plugin_bupt_charge").joinpath("data/stations.json")
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("stations"), list):
        raise ValueError("站点清单格式无效")
    stations: list[Station] = []
    numbers: set[int] = set()
    serials: set[str] = set()
    for item in payload["stations"]:
        if not isinstance(item, dict):
            raise ValueError("站点清单包含无效条目")
        try:
            station = Station(
                station_no=item["stationNo"],
                campus=item["campus"],
                location=item["location"],
                sn=item["sn"],
                socket_count=item["socketCount"],
                gps_id=item.get("gpsId"),
                marked_new=item.get("markedNew", False),
            )
        except (KeyError, TypeError) as error:
            raise ValueError("站点清单包含无效条目") from error
        if (
            type(station.station_no) is not int
            or station.station_no <= 0
            or not isinstance(station.campus, str)
            or not station.campus.strip()
            or not isinstance(station.location, str)
            or not station.location.strip()
            or not isinstance(station.sn, str)
            or re.fullmatch(r"\d{8,16}", station.sn) is None
            or type(station.socket_count) is not int
            or station.socket_count <= 0
            or (station.gps_id is not None and (
                type(station.gps_id) is not int or station.gps_id <= 0
            ))
            or type(station.marked_new) is not bool
            or station.station_no in numbers
            or station.sn in serials
        ):
            raise ValueError("站点清单包含无效或重复的站点")
        stations.append(station)
        numbers.add(station.station_no)
        serials.add(station.sn)
    return tuple(sorted(stations, key=lambda station: station.station_no))


_DIGITS = {
    "〇": "0", "零": "0", "一": "1", "二": "2", "两": "2", "三": "3",
    "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
}
_NUMERAL = re.compile(r"[〇零一二两三四五六七八九十]+")
_TENS = re.compile(r"([一二两三四五六七八九]?)十([一二两三四五六七八九]?)")


def normalize_search_text(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        numeral = match.group(0)
        tens = _TENS.fullmatch(numeral)
        if tens:
            ten = int(_DIGITS[tens[1]]) if tens[1] else 1
            one = int(_DIGITS[tens[2]]) if tens[2] else 0
            return str(ten * 10 + one)
        if "十" in numeral:
            return numeral
        return "".join(_DIGITS.get(char, char) for char in numeral)

    return _NUMERAL.sub(replace, unicodedata.normalize("NFKC", value).lower())


def campus_for_search(search: str) -> str | None:
    return {
        "海淀": "海淀校区", "海淀校区": "海淀校区",
        "沙河": "沙河校区", "沙河校区": "沙河校区",
    }.get(normalize_search_text(search.strip()))


def requires_narrowing(search: str, match_count: int) -> bool:
    return match_count > 15 and campus_for_search(search) is None


def match_stations(stations: Sequence[Station], search: str) -> list[Station]:
    normalized = normalize_search_text(search.strip())
    campus = campus_for_search(normalized)
    if campus:
        return [
            station for station in stations
            if station.campus == campus
            or (campus == "海淀校区" and station.campus == "小西天")
        ]
    number = re.fullmatch(r"(\d+)(?:号(?:站)?)?", normalized)
    if number:
        return [s for s in stations if s.station_no == int(number[1])]
    terms = normalized.split()
    if not terms:
        return []
    return [
        station for station in stations
        if all(term in normalize_search_text(
            f"{station.station_no}号站{station.campus}{station.location}"
        ) for term in terms)
    ]


def usage(stations: Sequence[Station]) -> str:
    haidian_count = sum(s.campus in ("海淀校区", "小西天") for s in stations)
    shahe_count = sum(s.campus == "沙河校区" for s in stations)
    return (
        f"已收录 {len(stations)} 台北邮充电桩："
        f"海淀（含小西天）{haidian_count} 台、沙河校区 {shahe_count} 台\n"
        "用法：/charge 17 或 /charge 学3 或 /charge 雁北 或 /charge 海淀 或 /charge 沙河 图书馆"
    )


def _port_numbers(ports: tuple[int, ...]) -> str:
    return "、".join(map(str, ports)) + "号" if ports else "无"


def format_single(snapshot: Snapshot) -> str:
    station = snapshot.station
    marker = "（新）" if station.marked_new else ""
    return (
        f"{station.station_no}{marker}号站 {station.location}（{station.campus}）\n"
        f"空闲 {len(snapshot.free_ports)}/{station.socket_count}："
        f"{_port_numbers(snapshot.free_ports)}"
    )


def summarize(snapshots: Sequence[Snapshot], failed: Sequence[int] = ()) -> tuple[str, str]:
    available = sorted(
        (snapshot for snapshot in snapshots if snapshot.free_ports),
        key=lambda snapshot: snapshot.station.station_no,
    )
    header = f"⚡查询到{sum(len(s.free_ports) for s in available)}个空闲插座"
    lines = [
        f"{s.station.station_no}号 {s.station.location}（{s.station.campus}） - "
        f"空闲 {len(s.free_ports)}/{s.station.socket_count}：{_port_numbers(s.free_ports)}"
        for s in available
    ]
    if not lines:
        lines.append("已查询的站点暂无空闲插口")
    if failed:
        lines.append("查询失败：" + "、".join(map(str, failed)) + "号站")
    return header, "\n".join(lines)


class ChargingClient:
    def __init__(
        self,
        base_url: str = "https://wx.jwnzn.com/njjwn",
        timeout_seconds: float = 8.0,
        cache_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("API URL 必须以 http:// 或 https:// 开头")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.cache_seconds = cache_seconds
        self.transport = transport
        self._cache: dict[str, tuple[float, Snapshot]] = {}
        self._pending: dict[str, asyncio.Task[Snapshot]] = {}
        self._lock = asyncio.Lock()

    async def query(self, station: Station) -> Snapshot:
        async with self._lock:
            cached = self._cache.get(station.sn)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            pending = self._pending.get(station.sn)
            if pending is None:
                pending = asyncio.create_task(self._request(station))
                self._pending[station.sn] = pending
        try:
            result = await pending
        finally:
            async with self._lock:
                if self._pending.get(station.sn) is pending:
                    self._pending.pop(station.sn)
                    if pending.done() and not pending.cancelled() and pending.exception() is None:
                        self._cache[station.sn] = (
                            time.monotonic() + self.cache_seconds, pending.result()
                        )
        return result

    async def _request(self, station: Station) -> Snapshot:
        query_value = f"gpsId:{station.gps_id or 58411};devType:2;sn:{station.sn};"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                response = await client.get(
                    f"{self.base_url}/eleProductList.action",
                    params={"queryValue": query_value},
                    headers={"Accept": "application/json"},
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise ChargingError(f"中网充返回 HTTP {response.status_code}")
            try:
                payload: Any = response.json()
            except ValueError as error:
                raise ChargingError("中网充未返回有效的插口列表") from error
            if not isinstance(payload, dict) or not isinstance(payload.get("list"), list):
                raise ChargingError("中网充未返回有效的插口列表")
            items = payload["list"]
            if len(items) != station.socket_count:
                raise ChargingError("中网充返回的插口数量与站点清单不符")
            free: list[int] = []
            busy: list[int] = []
            faulty: list[int] = []
            seen: set[int] = set()
            for item in items:
                if not isinstance(item, dict):
                    raise ChargingError("中网充返回了无效插口")
                try:
                    sid = int(item["sid"])
                    status_id = int(item["statusId"])
                except (KeyError, TypeError, ValueError) as error:
                    raise ChargingError("中网充返回了无效插口") from error
                if sid < 1 or sid > station.socket_count or sid in seen:
                    raise ChargingError("中网充返回了重复或越界的插口号")
                seen.add(sid)
                if status_id == 0:
                    free.append(sid)
                elif status_id == 1:
                    busy.append(sid)
                elif status_id == 2:
                    faulty.append(sid)
            return Snapshot(
                station, tuple(sorted(free)), tuple(sorted(busy)), tuple(sorted(faulty))
            )
        except httpx.TimeoutException as error:
            raise ChargingError("查询超时") from error
        except httpx.RequestError as error:
            raise ChargingError("无法连接中网充") from error
