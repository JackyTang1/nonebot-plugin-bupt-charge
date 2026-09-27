"""BUPT charging-station availability for NoneBot 2 / OneBot V11."""

from __future__ import annotations

import asyncio

from nonebot import get_plugin_config, on_command
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from .config import Config
from .core import (
    ChargingClient,
    ChargingError,
    format_single,
    load_stations,
    match_stations,
    requires_narrowing,
    summarize,
    usage,
)

__plugin_meta__ = PluginMetadata(
    name="北邮充电桩空闲插口查询",
    description="查询已收录北邮中网充设备的空闲插口，无需 Cookie。",
    usage="/charge 站号或地点；例如 /charge 17、/charge 学三、/charge 海淀",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

config = get_plugin_config(Config)
stations = load_stations()
client = ChargingClient(
    base_url=config.bupt_charge_api_url,
    timeout_seconds=config.bupt_charge_timeout_seconds,
    cache_seconds=config.bupt_charge_cache_seconds,
)
charge = on_command("charge", aliases={"充电桩"}, priority=10, block=True)


def _forward_nodes(header: str, body: str, self_id: str) -> list[dict[str, object]]:
    return [
        {
            "type": "node",
            "data": {"name": "北邮充电桩", "uin": int(self_id), "content": content},
        }
        for content in (header, body)
    ]


@charge.handle()
async def handle_charge(
    bot: Bot, event: MessageEvent, args: Message = CommandArg()
) -> None:
    search = args.extract_plain_text().strip()
    if not search:
        await charge.finish(usage(stations))

    matches = match_stations(stations, search)
    if not matches:
        await charge.finish("未收录匹配的北邮充电桩；可用 /charge 查看用法")
    if requires_narrowing(search, len(matches)):
        await charge.finish(
            f"匹配 {len(matches)} 台，请加地点关键词缩小范围，例如 /charge 海淀 学3"
        )

    if len(matches) == 1:
        try:
            snapshot = await client.query(matches[0])
        except ChargingError as error:
            await charge.finish(f"充电桩查询失败：{error}")
        await charge.finish(format_single(snapshot))

    semaphore = asyncio.Semaphore(3)

    async def query_one(station):
        async with semaphore:
            return await client.query(station)

    results = await asyncio.gather(
        *(query_one(station) for station in matches), return_exceptions=True
    )
    snapshots = []
    failed = []
    for station, result in zip(matches, results):
        if isinstance(result, BaseException):
            failed.append(station.station_no)
        else:
            snapshots.append(result)

    header, body = summarize(snapshots, failed)
    nodes = _forward_nodes(header, body, bot.self_id)
    try:
        if isinstance(event, GroupMessageEvent):
            await bot.call_api(
                "send_group_forward_msg", group_id=event.group_id, messages=nodes
            )
        else:
            await bot.call_api(
                "send_private_forward_msg", user_id=event.user_id, messages=nodes
            )
    except Exception:
        await charge.send(
            f"{header}\n{body}\n（合并转发发送失败，已改用普通消息）"
        )
