/**
 * 登录门禁中间件。
 *
 * 策略：只检查 session cookie（tdk_session）存在与否，不在此处做远端校验，
 * 避免每个请求都打 backend；远端校验在 server 端 requireUser()
 * 与 src/app/api/_guard.ts 的 assertSession() 内完成。
 *
 * matcher 放行：
 * - /login 精确路径段（/login、/login/... 放行；/login-foo 等仍走鉴权）；
 * - /api/auth/*（登录/注册/登出自身）；
 * - /_next/*（构建产物）、/favicon.ico；
 * - 带静态资源扩展名的路径（svg/png/ico/jpg/webp/css/js/map/txt/xml/woff2 等）。
 */
import { NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "tdk_session";

export function middleware(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) {
    return NextResponse.next();
  }
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.search = "";
  const { pathname, search } = request.nextUrl;
  if (pathname !== "/") {
    loginUrl.searchParams.set("next", pathname + search);
  }
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: [
    "/((?!login(?:/|$)|api/auth|_next|favicon.ico|.*\\.(?:svg|png|ico|jpe?g|gif|webp|avif|css|js|mjs|map|txt|xml|json|woff2?|ttf|otf)).*)",
  ],
};
