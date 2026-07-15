# 板块资金流导入与查询设计

## 目标

AMStock 新增独立的 `sector-flow` 命令组，用于手动导入东方财富风格的板块资金流 TXT 文件，并查询已持久化的历史快照。该功能与用户持仓账本相互独立。

## CLI 接口

```bash
uv run amstock sector-flow import --file /path/flow.txt
uv run amstock sector-flow import --file /path/flow.txt --date 2026-07-15
uv run amstock sector-flow list
uv run amstock sector-flow list --date 2026-07-15 --direction out --limit 30
uv run amstock sector-flow list --code BK1106
```

`import` 的 `--date` 可选；未指定时使用运行当日（`YYYY-MM-DD`）。文件名不参与日期推断。`list` 默认查询运行当日，可用 `--date`、`--code`、`--direction in|out` 与 `--limit` 筛选。结果按主力净流入升序，流出最强的板块优先。

所有命令沿用项目现有惯例，向标准输出写入一个 JSON 对象。

## 数据模型

新增 `sector_flow_records` 表，唯一键为 `(flow_date, sector_code)`。每条记录保存：

- 日期、板块代码、板块名称、最新值与涨幅百分比；
- 主力净流入与集合竞价；
- 超大单、大单、中单、小单各自的流入、流出、净额与净占比；
- 创建与更新时间戳。

所有金额统一转换为元并以 SQLAlchemy `Numeric`/Python `Decimal` 保存。解析器支持 `亿`（乘以 100,000,000）和 `万`（乘以 10,000），并保留正负号；因此同一列中混用单位仍可正确排序和比较。查询 JSON 同时给出精确 `*_yuan` 值及适合阅读的 `*_display` 值。

## 导入流程

1. 读取文件，按 UTF-8、GB18030、GBK 顺序尝试解码。
2. 根据中文表头定位所需列，而不是依赖固定列宽；空白分隔的文件行解析为 Python 中间表（数据类记录列表）。
3. 中间表构建期间完成每行字段、日期、金额单位与百分比校验。任何错误都包含行号，且不会开始数据库写入。
4. 中间表全部成功后，开启一个 SQLite 事务，对同一天同一板块代码批量 upsert。重复导入安全；文件中未出现的既有同日记录不删除。
5. 成功 JSON 返回导入日期、读取行数和写入/更新数。

## 模块边界

- `sector_flow_io.py`：无数据库依赖的解码、表头映射、金额换算与中间表构建。
- `models/sector_flow.py`：ORM 表定义。
- `repositories/sector_flow.py`：批量 upsert 与查询语句。
- `services/sector_flow.py`：日期、筛选与事务编排。
- `sector_flow_cli.py`：Typer `import` 与 `list` 命令；统一 CLI 挂载为 `sector-flow`。

## 错误处理与测试

未知编码、缺失/未知列、格式错误的数值、未知金额单位、无效日期和无效筛选参数均返回项目标准 JSON 错误；解析或写入失败必须回滚。

测试覆盖 GBK 样本、`万`/`亿`/负数换算、全量解析后写入、日期默认与覆盖、同日 upsert、方向筛选和排序、以及格式错误时 SQLite 无任何新增或更新。
