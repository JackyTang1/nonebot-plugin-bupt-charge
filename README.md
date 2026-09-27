# nonebot-plugin-bupt-charge

查询北邮已收录的中网充充电设备空闲插口（仅限电动自行车）并以 QQ 合并转发消息展示，适用于 NoneBot 2 + OneBot V11（例如 NapCat）。

## 功能

- `/charge`、`/充电桩`：查看用法和已收录数量。
- `/charge 17`：根据站号查询单台设备。
- `/charge 学3`、`/charge 学三`、`/charge 雁北`：按地点搜索，汉字/阿拉伯/全角数字等价。
- `/charge 海淀`、`/charge 沙河`：查询相应区域全部已收录站点的空闲插口；海淀包含小西天（南区教学楼）的 2 台。
- `/charge 沙河 图书馆`：多个关键词同时筛选。

设备状态实时查询，缓存 30 秒。校区查询不受 15 台限制，其他地点搜索一次最多查询 15 台，并发最多 3 个。只返回有空闲插口的站点。

目前收录已有的 59 台（1–7、12–57、60–65 号站）充电桩。若有变动欢迎 pr，可参考[充电桩变动](#充电桩变动)一节。


## 安装与启用

需要 Python 3.10+、NoneBot 2 和 OneBot V11 适配器。可在 NoneBot 项目环境中安装这个本地目录：

```bash
pip install -e /path/to/nonebot-plugin-bupt-charge
```

再在 NoneBot 项目的 `pyproject.toml` 中加载插件：

```toml
[tool.nonebot]
plugins = ["nonebot_plugin_bupt_charge"]
```

## 配置与权限

无需任何 Cookie 或 Token。可选设置如下：

```dotenv
BUPT_CHARGE_API_URL=https://wx.jwnzn.com/njjwn
BUPT_CHARGE_TIMEOUT_SECONDS=8
BUPT_CHARGE_CACHE_SECONDS=30
```

## 充电桩变动

新增站点的数据位于 [`nonebot_plugin_bupt_charge/data/stations.json`](nonebot_plugin_bupt_charge/data/stations.json) 的 `stations` 数组。

在数组中按站号插入一条记录，例如（**以下仅示例**）：

```json
{ "stationNo": 66, "campus": "海淀校区", "location": "学3楼北侧东户外", "sn": "12345678901", "socketCount": 10 }
```

- `stationNo`：站号，正整数且不能与已有站号重复。
- `campus`：校区名称。现有统计按 `海淀校区`、`沙河校区`、`小西天` 分组；如果增加新校区，还要修改 `core.py` 中 `usage()` 的校区列表。
- `location`：供回复展示和地点关键词匹配的位置描述，应从充电桩名称截取。
- `sn`：设备编号，**字符串**形式的 8–16 位数字，不能与已有设备编号重复。
- `socketCount`：该设备实际插座数量，正整数，必须与接口返回的插口列表长度一致，一般为 10。
- 可选 `gpsId`：已确认的正整数定位 ID；不填写时查询会使用现有兼容值 `58411`，若新设备查询失败应核实它的真实 `gpsId`。
- 可选 `markedNew`：布尔值 `true` 表示单站回复的站号带“（新）”标记，默认 `false`。

站号、充电桩名称、设备编号及实际插座数量均可从 `中网充` 小程序的充电桩详情页查询到。

新增后请同步修改本 README 上方的收录总数与站号范围，以及 [`tests/test_core.py`](tests/test_core.py) 中写死的 `59` 和相应断言。然后在项目目录运行：

```powershell
uv run --no-project --with-editable '.[test]' python -m pytest -q
```

测试通过后重启 NoneBot，并用 `/charge 新站号` 实查；出现“插口数量与站点清单不符”时先核对 `socketCount`、`sn` 和 `gpsId`。
