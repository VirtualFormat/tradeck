/** 兼容旧入口：统一迁移到宏观工作区的市场结构视图。 */
import { redirect } from "next/navigation";

export default function GlobalMacroPage() {
  redirect("/macro?view=structure");
}
