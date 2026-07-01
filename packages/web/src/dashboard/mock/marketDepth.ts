import { useEffect, useMemo, useState } from 'react';
import type { Market } from '../market';

export interface MockStock {
  id: string;
  symbol: string;
  name: string;
  sectorId: string;
  price: number;
  changePct: number;
  turnover: number;
  volume: number;
}

export interface MockSector {
  id: string;
  name: string;
  market: Market;
  indexValue: number;
  changePct: number;
  turnover: number;
  heat: number;
  marketCap: number;
  history: number[];
  stocks: MockStock[];
}

interface StockSeed {
  symbol: string;
  name: string;
  price: number;
  bias: number;
  turnover: number;
}

interface SectorSeed {
  id: string;
  name: string;
  index: number;
  drift: number;
  turnover: number;
  marketCap: number;
  stocks: StockSeed[];
}

const SEEDS: Record<Market, SectorSeed[]> = {
  cn: [
    {
      id: 'cn-ai',
      name: '人工智能',
      index: 1842,
      drift: 0.012,
      turnover: 128_000_000_000,
      marketCap: 3_400_000_000_000,
      stocks: [
        { symbol: '300308', name: '中际旭创', price: 186.24, bias: 0.018, turnover: 15_800_000_000 },
        { symbol: '688256', name: '寒武纪', price: 812.5, bias: 0.012, turnover: 11_200_000_000 },
        { symbol: '002230', name: '科大讯飞', price: 49.13, bias: 0.006, turnover: 7_600_000_000 },
        { symbol: '300502', name: '新易盛', price: 141.37, bias: 0.015, turnover: 9_800_000_000 },
        { symbol: '688041', name: '海光信息', price: 102.74, bias: -0.004, turnover: 8_300_000_000 },
        { symbol: '603019', name: '中科曙光', price: 69.82, bias: 0.003, turnover: 7_900_000_000 },
      ],
    },
    {
      id: 'cn-ev',
      name: '新能源车',
      index: 1327,
      drift: -0.006,
      turnover: 97_000_000_000,
      marketCap: 2_700_000_000_000,
      stocks: [
        { symbol: '002594', name: '比亚迪', price: 298.7, bias: -0.002, turnover: 9_700_000_000 },
        { symbol: '300750', name: '宁德时代', price: 231.43, bias: -0.008, turnover: 12_100_000_000 },
        { symbol: '601633', name: '长城汽车', price: 26.1, bias: 0.005, turnover: 3_900_000_000 },
        { symbol: '600104', name: '上汽集团', price: 16.22, bias: -0.006, turnover: 2_700_000_000 },
        { symbol: '002050', name: '三花智控', price: 31.9, bias: 0.011, turnover: 5_100_000_000 },
        { symbol: '603806', name: '福斯特', price: 18.38, bias: -0.012, turnover: 2_100_000_000 },
      ],
    },
    {
      id: 'cn-semi',
      name: '半导体',
      index: 2114,
      drift: 0.004,
      turnover: 112_000_000_000,
      marketCap: 2_900_000_000_000,
      stocks: [
        { symbol: '688981', name: '中芯国际', price: 87.46, bias: 0.006, turnover: 13_800_000_000 },
        { symbol: '603501', name: '韦尔股份', price: 116.35, bias: 0.003, turnover: 5_600_000_000 },
        { symbol: '688012', name: '中微公司', price: 179.2, bias: 0.012, turnover: 4_400_000_000 },
        { symbol: '002371', name: '北方华创', price: 346.1, bias: -0.004, turnover: 7_900_000_000 },
        { symbol: '300661', name: '圣邦股份', price: 82.78, bias: -0.009, turnover: 2_600_000_000 },
        { symbol: '688008', name: '澜起科技', price: 71.55, bias: 0.007, turnover: 4_900_000_000 },
      ],
    },
    {
      id: 'cn-finance',
      name: '大金融',
      index: 987,
      drift: -0.002,
      turnover: 84_000_000_000,
      marketCap: 5_600_000_000_000,
      stocks: [
        { symbol: '600030', name: '中信证券', price: 27.38, bias: 0.002, turnover: 6_300_000_000 },
        { symbol: '601318', name: '中国平安', price: 51.72, bias: -0.005, turnover: 5_700_000_000 },
        { symbol: '600036', name: '招商银行', price: 38.94, bias: -0.003, turnover: 4_800_000_000 },
        { symbol: '601166', name: '兴业银行', price: 20.18, bias: 0.004, turnover: 3_900_000_000 },
        { symbol: '601688', name: '华泰证券', price: 18.41, bias: 0.008, turnover: 3_400_000_000 },
        { symbol: '601601', name: '中国太保', price: 33.12, bias: -0.007, turnover: 2_800_000_000 },
      ],
    },
    {
      id: 'cn-consume',
      name: '消费电子',
      index: 1568,
      drift: 0.007,
      turnover: 76_000_000_000,
      marketCap: 1_900_000_000_000,
      stocks: [
        { symbol: '002475', name: '立讯精密', price: 43.26, bias: 0.012, turnover: 6_900_000_000 },
        { symbol: '000725', name: '京东方A', price: 4.21, bias: -0.002, turnover: 4_200_000_000 },
        { symbol: '300433', name: '蓝思科技', price: 25.47, bias: 0.008, turnover: 4_000_000_000 },
        { symbol: '002241', name: '歌尔股份', price: 24.58, bias: 0.003, turnover: 4_600_000_000 },
        { symbol: '603986', name: '兆易创新', price: 118.64, bias: -0.006, turnover: 3_700_000_000 },
        { symbol: '300866', name: '安克创新', price: 92.1, bias: 0.01, turnover: 2_400_000_000 },
      ],
    },
  ],
  hk: [
    {
      id: 'hk-tech',
      name: '港股科技',
      index: 4216,
      drift: 0.009,
      turnover: 72_000_000_000,
      marketCap: 4_800_000_000_000,
      stocks: [
        { symbol: '00700', name: '腾讯控股', price: 421.6, bias: 0.006, turnover: 13_400_000_000 },
        { symbol: '09988', name: '阿里巴巴-W', price: 86.7, bias: 0.011, turnover: 9_600_000_000 },
        { symbol: '03690', name: '美团-W', price: 118.5, bias: -0.003, turnover: 8_900_000_000 },
        { symbol: '09888', name: '百度集团-SW', price: 91.8, bias: 0.004, turnover: 3_500_000_000 },
        { symbol: '09618', name: '京东集团-SW', price: 131.2, bias: -0.006, turnover: 4_800_000_000 },
        { symbol: '01810', name: '小米集团-W', price: 35.4, bias: 0.014, turnover: 7_100_000_000 },
      ],
    },
    {
      id: 'hk-finance',
      name: '港股金融',
      index: 3188,
      drift: -0.003,
      turnover: 55_000_000_000,
      marketCap: 6_200_000_000_000,
      stocks: [
        { symbol: '00005', name: '汇丰控股', price: 84.3, bias: -0.004, turnover: 5_400_000_000 },
        { symbol: '02318', name: '中国平安', price: 48.6, bias: -0.007, turnover: 4_900_000_000 },
        { symbol: '03988', name: '中国银行', price: 4.32, bias: 0.002, turnover: 3_700_000_000 },
        { symbol: '01299', name: '友邦保险', price: 62.15, bias: -0.005, turnover: 4_300_000_000 },
        { symbol: '01398', name: '工商银行', price: 5.62, bias: 0.003, turnover: 4_100_000_000 },
        { symbol: '00388', name: '香港交易所', price: 342.8, bias: 0.006, turnover: 5_200_000_000 },
      ],
    },
    {
      id: 'hk-biotech',
      name: '创新药',
      index: 912,
      drift: 0.004,
      turnover: 38_000_000_000,
      marketCap: 1_100_000_000_000,
      stocks: [
        { symbol: '02269', name: '药明生物', price: 15.78, bias: 0.011, turnover: 3_600_000_000 },
        { symbol: '06160', name: '百济神州', price: 124.1, bias: 0.005, turnover: 2_900_000_000 },
        { symbol: '01801', name: '信达生物', price: 42.65, bias: -0.008, turnover: 2_700_000_000 },
        { symbol: '01093', name: '石药集团', price: 6.34, bias: -0.003, turnover: 1_800_000_000 },
        { symbol: '01177', name: '中国生物制药', price: 3.18, bias: 0.002, turnover: 1_500_000_000 },
        { symbol: '09926', name: '康方生物', price: 76.2, bias: 0.014, turnover: 3_200_000_000 },
      ],
    },
  ],
  us: [
    {
      id: 'us-megacap',
      name: '美股科技龙头',
      index: 6742,
      drift: 0.006,
      turnover: 91_000_000_000,
      marketCap: 15_600_000_000_000,
      stocks: [
        { symbol: 'NVDA', name: 'NVIDIA', price: 152.4, bias: 0.012, turnover: 18_300_000_000 },
        { symbol: 'MSFT', name: 'Microsoft', price: 497.8, bias: 0.004, turnover: 8_700_000_000 },
        { symbol: 'AAPL', name: 'Apple', price: 214.6, bias: -0.003, turnover: 9_900_000_000 },
        { symbol: 'GOOGL', name: 'Alphabet', price: 187.3, bias: 0.005, turnover: 6_600_000_000 },
        { symbol: 'META', name: 'Meta', price: 701.1, bias: 0.009, turnover: 7_200_000_000 },
        { symbol: 'TSLA', name: 'Tesla', price: 318.6, bias: -0.011, turnover: 12_400_000_000 },
      ],
    },
    {
      id: 'us-ai-infra',
      name: 'AI基础设施',
      index: 2448,
      drift: 0.013,
      turnover: 66_000_000_000,
      marketCap: 3_900_000_000_000,
      stocks: [
        { symbol: 'AVGO', name: 'Broadcom', price: 284.9, bias: 0.014, turnover: 7_500_000_000 },
        { symbol: 'AMD', name: 'AMD', price: 178.2, bias: 0.008, turnover: 6_900_000_000 },
        { symbol: 'MU', name: 'Micron', price: 131.7, bias: 0.006, turnover: 5_800_000_000 },
        { symbol: 'SMCI', name: 'Super Micro', price: 49.3, bias: -0.009, turnover: 3_800_000_000 },
        { symbol: 'ORCL', name: 'Oracle', price: 214.1, bias: 0.004, turnover: 4_600_000_000 },
        { symbol: 'PLTR', name: 'Palantir', price: 142.8, bias: 0.017, turnover: 7_300_000_000 },
      ],
    },
    {
      id: 'us-finance',
      name: '美股金融',
      index: 1896,
      drift: -0.004,
      turnover: 43_000_000_000,
      marketCap: 4_200_000_000_000,
      stocks: [
        { symbol: 'JPM', name: 'JPMorgan', price: 286.4, bias: 0.002, turnover: 3_900_000_000 },
        { symbol: 'BAC', name: 'Bank of America', price: 47.2, bias: -0.005, turnover: 3_300_000_000 },
        { symbol: 'GS', name: 'Goldman Sachs', price: 682.7, bias: -0.004, turnover: 2_800_000_000 },
        { symbol: 'MS', name: 'Morgan Stanley', price: 139.5, bias: 0.003, turnover: 2_400_000_000 },
        { symbol: 'V', name: 'Visa', price: 355.2, bias: 0.004, turnover: 2_900_000_000 },
        { symbol: 'MA', name: 'Mastercard', price: 568.6, bias: -0.002, turnover: 2_200_000_000 },
      ],
    },
  ],
};

function wave(tick: number, phase: number, scale: number): number {
  return Math.sin(tick * 0.65 + phase) * scale + Math.cos(tick * 0.28 + phase * 0.7) * scale * 0.45;
}

function buildSectors(market: Market, tick: number): MockSector[] {
  return SEEDS[market].map((sector, sectorIndex) => {
    const changePct = sector.drift + wave(tick, sectorIndex + 1.5, 0.008);
    const heat = Math.max(12, Math.min(99, 52 + changePct * 1800 + Math.sin(tick + sectorIndex) * 8));
    const history = Array.from({ length: 46 }, (_, i) => {
      const age = 45 - i;
      const local = changePct - wave(tick - age * 0.12, sectorIndex + 0.3, 0.006);
      return sector.index * (1 + local);
    });
    const turnover = sector.turnover * (1 + Math.abs(changePct) * 9 + wave(tick, sectorIndex + 3, 0.045));
    const stocks = sector.stocks.map((stock, stockIndex) => {
      const stockChange = changePct + stock.bias + wave(tick, sectorIndex * 2 + stockIndex, 0.011);
      return {
        id: `${sector.id}-${stock.symbol}`,
        symbol: stock.symbol,
        name: stock.name,
        sectorId: sector.id,
        price: stock.price * (1 + stockChange),
        changePct: stockChange,
        turnover: stock.turnover * (1 + Math.abs(stockChange) * 11 + wave(tick, stockIndex + 4, 0.04)),
        volume: stock.turnover / stock.price,
      };
    });
    return {
      id: sector.id,
      name: sector.name,
      market,
      indexValue: sector.index * (1 + changePct),
      changePct,
      turnover,
      heat,
      marketCap: sector.marketCap,
      history,
      stocks,
    };
  });
}

export function useMockMarketDepth(market: Market, enabled = true): MockSector[] {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!enabled) return undefined;
    const timer = setInterval(() => setTick((n) => n + 1), 1600);
    return () => clearInterval(timer);
  }, [enabled]);

  return useMemo(() => buildSectors(market, tick), [market, tick]);
}
