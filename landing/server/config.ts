import { z } from 'zod';

const configSchema = z.object({
  PORT: z.coerce.number().default(5174),
  NODE_ENV: z.enum(['development', 'production', 'test']).default('development'),
});

export type AppConfig = z.infer<typeof configSchema>;

export const loadConfig = {
  from: {
    env: (env: unknown) => configSchema.parse(env),
  },
};
