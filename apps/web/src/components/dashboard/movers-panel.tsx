/**
 * 首页异动榜数据边界（Server Component）
 * 当前市场四类榜单并发预取后一次传给 Client Tabs，浏览器不连接 backend。
 */
import {
  fetchMoversPrimaryData,
  fetchMoversTurnover,
  type MoversItem,
  type MoversMarket,
  type MoversType,
} from "@/lib/openbb";

import { MoversTabs } from "./movers-tabs";

export type MoversData = Record<MoversType, MoversItem[]>;

const MAX_ROWS = 6;

export async function MoversPanel({
  market,
  date,
}: {
  market: MoversMarket;
  date?: string;
}) {
  const [primary, turnover] = await Promise.all([
    fetchMoversPrimaryData(market, date, MAX_ROWS),
    fetchMoversTurnover(market, MAX_ROWS),
  ]);

  const data: MoversData = {
    ...primary,
    turnover,
  };

  return <MoversTabs market={market} date={date} data={data} />;
}
