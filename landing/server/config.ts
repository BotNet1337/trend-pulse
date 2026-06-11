import { z } from 'zod';

const configSchema = z.object({
  PORT: z.coerce.number().default(5174),
  NODE_ENV: z.enum(['development', 'production', 'test']).default('development'),
  // TASK-067: SSR-side fetch of public GET /api/v1/cases (proof-of-speed section).
  // Empty CASES_API_URL = feature disabled, section hidden.
  CASES_API_URL: z.string().default(''),
  CASES_CACHE_TTL_SECONDS: z.coerce.number().int().positive().default(300),
  CASES_FETCH_TIMEOUT_MS: z.coerce.number().int().positive().default(2000),
});

export type AppConfig = z.infer<typeof configSchema>;

export const loadConfig = {
  from: {
    env: (env: unknown) => configSchema.parse(env),
  },
};
