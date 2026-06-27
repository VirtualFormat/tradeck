import { BadRequestException, Body, Controller, Get, Put } from '@nestjs/common';
import { type DashboardLayout, DashboardLayoutSchema } from '@tradeck/shared';
import { DashboardService } from './dashboard.service';

@Controller('api')
export class DashboardController {
  constructor(private readonly svc: DashboardService) {}

  @Get('dashboard/layout')
  get(): Promise<DashboardLayout> {
    return this.svc.getLayout();
  }

  @Put('dashboard/layout')
  save(@Body() body: unknown): Promise<DashboardLayout> {
    const parsed = DashboardLayoutSchema.safeParse(body);
    if (!parsed.success) {
      throw new BadRequestException(parsed.error.issues.map((i) => i.message));
    }
    return this.svc.saveLayout(parsed.data);
  }
}
