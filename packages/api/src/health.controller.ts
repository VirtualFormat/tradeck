import { Controller, Get } from '@nestjs/common';

@Controller('health')
export class HealthController {
  @Get()
  check(): { status: string; ts: number } {
    return { status: 'ok', ts: Date.now() };
  }
}
