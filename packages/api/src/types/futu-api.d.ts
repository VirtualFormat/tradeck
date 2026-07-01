declare module 'futu-api' {
  export interface FutuResponse {
    retType?: number;
    retMsg?: string;
    errCode?: number;
    s2c?: Record<string, unknown>;
  }

  export default class FutuWebsocket {
    onlogin: ((ret: boolean, msg: unknown) => void) | null;
    onPush: ((cmd: number, payload: FutuResponse) => void) | null;
    start(ip: string, port: number, ssl?: boolean, key?: string): void;
    stop(): void;
    Sub(req: unknown): Promise<FutuResponse>;
    GetBasicQot(req: unknown): Promise<FutuResponse>;
    GetHeatMapData(req: unknown): Promise<FutuResponse>;
    GetPlateSecurity(req: unknown): Promise<FutuResponse>;
  }
}
