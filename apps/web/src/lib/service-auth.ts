/**
 * 消费方鉴权头（web 作为 tradb data-api / collector 的消费方）。
 *
 * tradb 配置 SERVICE_TOKENS 后所有接口要求有效 X-Service-Token；
 * web 侧从环境变量读 TRADB_SERVICE_TOKEN / TRADB_SERVICE_NAME（默认 web-bff），
 * token 为空则不加这两个头（向后兼容内网无鉴权）。
 *
 * 安全：仅服务端（Server Component / Next 代理 route.ts，Node 运行时）注入，
 * 严禁在 "use client" 组件中使用本模块——token 绝不能进浏览器包。
 */

const TRADB_SERVICE_TOKEN = process.env.TRADB_SERVICE_TOKEN ?? "";
const TRADB_SERVICE_NAME = process.env.TRADB_SERVICE_NAME ?? "web-bff";

/** 指向 data-api / collector 的服务端 fetch 统一携带的消费方身份头。 */
export function serviceAuthHeaders(): Record<string, string> {
  if (!TRADB_SERVICE_TOKEN) return {};
  return {
    "X-Service-Token": TRADB_SERVICE_TOKEN,
    "X-Service-Name": TRADB_SERVICE_NAME,
  };
}
