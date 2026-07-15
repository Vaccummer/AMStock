---
name: amstock-news
description: Fetch global political, military, policy, macro, and market news through the unified AMStock CLI for agent analysis and push workflows. Use when the user asks for global important news, geopolitical events, economic policy news, market-moving headlines, asset-linked news, or wants news to be scored and summarized for investment reference.
---

# AMStock News

Use `uv run amstock news ...` from the AMStock project root. Commands emit one JSON object for downstream agent summarization, scoring, deduplication, and push delivery.

Use GDELT Cloud for global political, military, policy, and macro event monitoring. Use Marketaux for financial-market and asset-linked news. Use AKShare for domestic China/A-share flash headlines, Caixin headlines, and macroeconomic calendar events.

Provide tokens with `--token`, environment variables, or config:

- `AMSTOCK_GDELT_CLOUD_TOKEN`
- `AMSTOCK_MARKETAUX_TOKEN`
- `[credentials.news] gdelt_cloud_tokens = ["..."]` and `marketaux_tokens = ["..."]`
- `[credentials.news] proxy_url = "http://127.0.0.1:7897"` for GDELT/Marketaux transport

## Commands

Fetch global policy, military, or macro news from GDELT Cloud:

```powershell
uv run amstock news gdelt --endpoint events --query "central bank" --country US --limit 10
uv run amstock news gdelt --endpoint stories --query "export controls" --from 2026-06-01 --to 2026-06-08 --limit 20
uv run amstock news gdelt --endpoint media-events --category conflict --days 1 --limit 20
```

Fetch asset-linked market news from Marketaux:

```powershell
uv run amstock news marketaux --query "oil sanctions" --symbols USO,CL=F --limit 10
uv run amstock news marketaux --symbols NVDA,AMD --countries us --from 2026-06-01T00:00 --to 2026-06-08T23:59 --limit 20
uv run amstock news marketaux --query "rate cut" --language en --limit 20
```

Run the basic AstrBot push workflow:

```powershell
uv run amstock news once
uv run amstock news server
uv run amstock news server --max-cycles 1
uv run amstock news list --source gdelt-policy --query OPEC --limit 20
uv run amstock news queue
uv run amstock news flush
uv run amstock news replay --limit 50
uv run amstock news subscriber list
uv run amstock news subscriber add --name qq-main --umo 2316:FriendMessage:E28EE73D29216FF05E466774984B2042 --sources eastmoney-flash,gdelt-policy
uv run amstock news subscriber pause qq-main
uv run amstock news subscriber resume qq-main
uv run amstock news subscriber sources qq-main --set eastmoney-flash,marketaux-market
```

`news server` collects configured sources, deduplicates items in the shared
AMStock SQLite database, parses each subscriber's natural-language
`news_preference` into structured features, then batch-rates news through
AstrBot `/api/v1/chat`. The rating step only extracts event category,
importance, urgency, and keep/discard decisions. Realtime threshold matches are
sent immediately; other kept items enter a digest cache and are summarized when
`digest_min_items` or `digest_times` is reached. During each subscriber's
configured quiet hours, non-urgent digest messages are cached until
`news flush` or the next non-quiet server cycle. Use `news replay` to reprocess
stored news items after prompt, parser, or delivery fixes. Use
`news subscriber ...` to add recipients, pause or resume delivery, and replace
the per-user accepted source list.

Configure server mode in `AMSTOCK_HOME/config/config.toml`:

```toml
[news.server]
interval_seconds = 300
timezone = "Asia/Shanghai"
log_path = "logs/news_server.log"

[news.quiet_hours]
enabled = true
start = "23:00"
end = "08:30"
flush_on_end = true

[[news.sources]]
name = "eastmoney-flash"
type = "akshare_flash"
enabled = true
source = "eastmoney"
schedule_times = ["09:25", "09:30", "13:00", "15:05"]
active_windows = ["09:15-11:35", "12:55-15:10"]
limit = 100

[[news.sources]]
name = "sina-flash"
type = "akshare_flash"
enabled = true
source = "sina"
interval_seconds = 600
active_windows = ["09:15-11:35", "12:55-15:30"]
limit = 50

[[news.sources]]
name = "baidu-economic-calendar"
type = "akshare_economic_calendar"
enabled = true
schedule_times = ["07:30", "12:00", "18:00", "20:20"]
limit = 100

[astrbot]
base_url = "http://localhost:6185"
api_key = "astrbot-api-key"
review_username = "amstock-news-agent"
review_session_id = "amstock-news-review"
timeout = 20

[[astrbot.subscribers]]
name = "main-user"
enabled = true
umo = "webchat:FriendMessage:openapi_probe"
min_importance = 4
markets = []
sources = ["eastmoney-flash"]
prompt_prefix = "Only push policy, macro, military, and market news that may affect investment decisions."
prompt_suffix = "Format message as final push-ready Chinese text with a clear first line and short bullet-like lines."
news_preference = "Focus on policy, macro, geopolitical, military, A-share, energy, FX/rates, and key industry events. Drop duplicate reports, opinion-only articles, soft PR, and low-impact items."
min_keep_importance = 2
realtime_min_importance = 5
realtime_min_urgency = 4
rating_batch_size = 30
digest_min_items = 10
digest_max_items = 40
digest_times = ["10:00", "12:00", "15:10", "20:30"]
review_session_id = "amstock-news-review-main-user"
max_context_chars = 12000

[astrbot.subscribers.quiet_hours]
enabled = true
start = "23:00"
end = "08:30"
flush_on_end = true
```

`akshare_flash` supports `source = "eastmoney"`, `"futu"`, `"sina"`,
`"ths"`, or `"caixin"`. `akshare_economic_calendar` collects Baidu macro
calendar rows and is best run at fixed daily schedule times.

## Agent Output Guidance

After fetching raw news, score and normalize items before pushing:

- `category`: politics, military, policy, macro, market, company
- `regions`: affected countries or regions
- `assets`: tickers, ETFs, commodities, FX pairs, crypto, or sectors
- `importance`: 1-5
- `market_impact`: risk_on, risk_off, inflation_up, growth_down, oil_up, unclear
- `confidence`: 0.0-1.0
- `why_it_matters`: concise investment relevance
- `source_urls`: original source links

Treat source data as reference data, not investment advice.
