"""Offline tests: no network, QQ login or Cookie required."""

from __future__ import annotations

import asyncio

import httpx
import nonebot
import pytest

nonebot.init()
assert nonebot.load_plugin("nonebot_plugin_bupt_charge") is not None

from nonebot_plugin_bupt_charge import _forward_nodes
from nonebot_plugin_bupt_charge.core import (
    ChargingClient,
    ChargingError,
    Snapshot,
    Station,
    campus_for_search,
    format_single,
    load_stations,
    match_stations,
    requires_narrowing,
    summarize,
    usage,
)


def test_catalog_and_help() -> None:
    stations = load_stations()
    assert len(stations) == 59
    assert len({station.station_no for station in stations}) == 59
    assert len({station.sn for station in stations}) == 59
    assert stations[0].station_no < stations[-1].station_no
    assert "已收录 59 台" in usage(stations)
    assert "海淀（含小西天）45 台、沙河校区 14 台" in usage(stations)
    assert "（部分站点）" not in usage(stations)


def test_search_normalization() -> None:
    stations = load_stations()
    same = [s.station_no for s in match_stations(stations, "学3")]
    assert same == [s.station_no for s in match_stations(stations, "学三")]
    assert same == [s.station_no for s in match_stations(stations, "学３")]
    assert [s.station_no for s in match_stations(stations, "三十")] == [30]
    assert [s.station_no for s in match_stations(stations, "沙河 图书馆")] == [7, 47, 48]
    assert match_stations(stations, "不存在的地点") == []


def test_exact_campus_search_is_not_a_broad_location_search() -> None:
    stations = load_stations()
    for search, campus, count in (
        ("海淀", "海淀校区", 45), ("海淀校区", "海淀校区", 45),
        ("沙河", "沙河校区", 14), ("沙河校区", "沙河校区", 14),
    ):
        assert campus_for_search(search) == campus
        matches = match_stations(stations, search)
        assert len(matches) == count
        assert not requires_narrowing(search, len(matches))
        allowed_campuses = {campus, "小西天"} if campus == "海淀校区" else {campus}
        assert all(station.campus in allowed_campuses for station in matches)
        if campus == "海淀校区":
            assert sum(station.campus == "小西天" for station in matches) == 2
    assert campus_for_search("海淀 学3") is None
    assert campus_for_search("沙河 图书馆") is None
    assert requires_narrowing("海淀 学3", 16)
    assert not requires_narrowing("海淀 学3", 15)


def test_format_free_ports_and_order() -> None:
    stations = load_stations()
    west = next(s for s in stations if s.station_no == 17)
    east = next(s for s in stations if s.station_no == 19)
    snapshots = [
        Snapshot(east, (1, 4, 5, 8), (2,), (3,)),
        Snapshot(west, (4, 6, 7, 8, 9), (1,), (2,)),
    ]
    header, body = summarize(snapshots)
    assert header == "⚡查询到9个空闲插座"
    assert body.splitlines()[0].startswith("17号 ")
    assert body.splitlines()[1].startswith("19号 ")
    assert "故障" not in body
    assert format_single(snapshots[1]).endswith("空闲 5/10：4、6、7、8、9号")
    assert _forward_nodes(header, body, "12345") == [
        {"type": "node", "data": {"name": "北邮充电桩", "uin": 12345, "content": header}},
        {"type": "node", "data": {"name": "北邮充电桩", "uin": 12345, "content": body}},
    ]


def test_query_is_anonymous_and_cached() -> None:
    station = Station(57, "海淀校区", "家属区14号楼东侧", "14985810541", 3, 58411)
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.params["queryValue"] == "gpsId:58411;devType:2;sn:14985810541;"
        assert "cookie" not in request.headers
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"list": [
            {"sid": 1, "statusId": 0},
            {"sid": 2, "statusId": 1},
            {"sid": 3, "statusId": 2},
        ]})

    async def run() -> None:
        client = ChargingClient(transport=httpx.MockTransport(respond))
        first, second = await asyncio.gather(client.query(station), client.query(station))
        assert first == second
        assert first.free_ports == (1,)
        assert first.faulty_ports == (3,)
        assert await client.query(station) == first

    asyncio.run(run())
    assert len(requests) == 1


def test_bad_response_is_not_reported_as_empty() -> None:
    station = Station(57, "海淀校区", "家属区14号楼东侧", "14985810541", 3)

    async def run() -> None:
        client = ChargingClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text="<html>expired</html>"))
        )
        with pytest.raises(ChargingError, match="未返回有效"):
            await client.query(station)

    asyncio.run(run())
