/**
 * 底部横排指标带（满宽）
 * 三块并列：宏观速览 · 大宗商品 · 国债收益率
 * 直接复用现有 MacroSnapshot / CommoditiesBoard / TreasuryBoard
 * （各组件自带内部小标题与数据时间标注、自带取数与优雅降级）
 * 本文件只负责满宽横排布局。
 */
import { MacroSnapshot } from "@/components/macro-snapshot";
import { CommoditiesBoard } from "@/components/commodities-board";
import { TreasuryBoard } from "@/components/treasury-board";

export async function MarketMetricsBand() {
  return (
    <div>
      <h2 className="mb-3 text-sm font-medium text-fg-dim">宏观 · 大宗 · 国债</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <MacroSnapshot />
        <CommoditiesBoard />
        <TreasuryBoard />
      </div>
    </div>
  );
}
