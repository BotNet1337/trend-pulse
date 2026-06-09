import type { ComponentType } from 'react';
import type { z } from 'zod';
import type { AppConfig } from './config.js';

export type TransformMap = Record<string, string>;

export interface RegistryEntry {
  schema: z.ZodType;
  Component: ComponentType<Record<string, unknown>>;
  subject: string;
  transformMap: TransformMap | null;
  previewDefaults: Record<string, unknown>;
}

declare module 'fastify' {
  interface FastifyInstance {
    appConfig: AppConfig;
    registry: Record<string, RegistryEntry>;
  }
}
