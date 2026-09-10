"""data-api 客户端 + Parquet 缓存层。

日K：client.fetch_bars + store（按标的缓存）；
分钟K：client.fetch_minute_bars + client_minute（按标的/年缓存，G3）。
"""
