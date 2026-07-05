#!/bin/bash
# OpenBB Platform 启动验证脚本（基于源码研究 + 实际测试）
# 用法：bash docker/openbb/verify.sh
set -e
OPENBB_URL="http://localhost:6900"

echo "=== OpenBB Platform 验证 ==="
echo ""

# 1. OpenAPI 路由总数
echo "1. 路由总数..."
ROUTE_COUNT=$(curl -sf "${OPENBB_URL}/openapi.json" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('paths',{})))" 2>/dev/null)
if [ -z "$ROUTE_COUNT" ]; then
    echo "   ❌ OpenBB 未响应"
    exit 1
fi
echo "   ✅ ${ROUTE_COUNT} 个路由已就绪"

# 2. Providers 数量
echo ""
echo "2. Providers..."
curl -sf "${OPENBB_URL}/api/v1/coverage/providers" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'   ✅ {len(d)} 个 Provider 已装')
print(f'   免费(无key): yfinance, sec, federal_reserve, cftc, ecb, imf, oecd, finviz, wsj, cboe...')
" 2>/dev/null

# 3. 美股报价（yfinance 免费源）
echo ""
echo "3. 美股报价 AAPL (yfinance)..."
curl -sf "${OPENBB_URL}/api/v1/equity/price/quote?provider=yfinance&symbol=AAPL" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
r=d.get('results',[{}])[0] if d.get('results') else {}
print(f'   symbol: {r.get(\"symbol\")}, name: {r.get(\"name\")}')
print(f'   price: {r.get(\"last_price\")} {r.get(\"currency\")}, volume: {r.get(\"volume\")}')
" 2>/dev/null

# 4. A 股报价（yfinance 免费源）
echo ""
echo "4. A 股报价 600519.SS 茅台 (yfinance)..."
curl -sf "${OPENBB_URL}/api/v1/equity/price/quote?provider=yfinance&symbol=600519.SS" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
r=d.get('results',[{}])[0] if d.get('results') else {}
print(f'   symbol: {r.get(\"symbol\")}, name: {r.get(\"name\")}')
print(f'   price: {r.get(\"last_price\")} {r.get(\"currency\")}')
" 2>/dev/null

# 5. 港股历史 K 线（yfinance 免费源）
echo ""
echo "5. 港股历史 0700.HK 腾讯 (yfinance)..."
curl -sf "${OPENBB_URL}/api/v1/equity/price/historical?provider=yfinance&symbol=0700.HK&start_date=2026-06-01&end_date=2026-07-01" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
results=d.get('results',[])
print(f'   条数: {len(results)}')
if results:
    r=results[0]
    print(f'   首条: {r.get(\"date\")} O={r.get(\"open\"):.2f} H={r.get(\"high\"):.2f} L={r.get(\"low\"):.2f} C={r.get(\"close\"):.2f}')
" 2>/dev/null

# 6. 美股财报（sec 免费源）
echo ""
echo "6. 美股财报 AAPL (sec)..."
curl -sf "${OPENBB_URL}/api/v1/equity/fundamental/income?provider=sec&symbol=AAPL&period=annual&limit=1" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
results=d.get('results',[])
print(f'   条数: {len(results)}')
if results:
    r=results[0]
    print(f'   fiscal_year: {r.get(\"fiscal_year\")}, revenue: {r.get(\"total_revenue\")}')
" 2>/dev/null

# 7. 宏观利率（federal_reserve 免费源）
echo ""
echo "7. 美国国债收益率 (federal_reserve)..."
curl -sf "${OPENBB_URL}/api/v1/economy/treasury_rates?provider=federal_reserve" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
results=d.get('results',[])
print(f'   条数: {len(results)}')
if results:
    r=results[-1]
    print(f'   date: {r.get(\"date\")}, 3m: {r.get(\"bc_3_month\")}, 10y: {r.get(\"bc_10_year\")}')
" 2>/dev/null

# 8. Swagger UI
echo ""
echo "8. Swagger UI..."
HTTP=$(curl -sf -o /dev/null -w "%{http_code}" "${OPENBB_URL}/docs" 2>/dev/null)
[ "$HTTP" = "200" ] && echo "   ✅ /docs 可访问" || echo "   ⚠️ /docs 返回 $HTTP"

echo ""
echo "=== 验证完成 ==="
echo "Swagger UI: ${OPENBB_URL}/docs"
echo "OpenAPI: ${OPENBB_URL}/openapi.json"
echo "Workspace: https://my.openbb.co/app/platform"
echo ""
echo "注意：news 端点只支持 benzinga/fmp/intrinio/tiingo（需 key）"
echo "     yfinance 不支持 news，Finnhub 也未集成进 OpenBB"
