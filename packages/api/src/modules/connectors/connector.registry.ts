import { Injectable } from '@nestjs/common';
import { BaseConnector } from './base.connector';

type ConnectorFactory = () => BaseConnector;

@Injectable()
export class ConnectorRegistry {
  private readonly factories = new Map<string, ConnectorFactory>();

  register(type: string, factory: ConnectorFactory): void {
    this.factories.set(type, factory);
  }

  create(type: string): BaseConnector {
    const factory = this.factories.get(type);
    if (!factory) throw new Error(`unknown connector type: ${type}`);
    return factory();
  }

  has(type: string): boolean {
    return this.factories.has(type);
  }
}
