/** Normal command connection: set / get / publish / queries. */
export const REDIS_CLIENT = 'REDIS_CLIENT';

/**
 * Dedicated subscribe connection. Once an ioredis connection enters
 * subscribe/psubscribe mode it can only handle subscription commands, so the
 * SSE gateway must use this one and never the REDIS_CLIENT.
 */
export const REDIS_SUBSCRIBER = 'REDIS_SUBSCRIBER';
