import { z } from 'zod';

const configSchema = z
  .object({
    PORT: z.coerce.number().default(3100),
    NODE_ENV: z.string().default('development'),
    FRONTEND_DOMAIN: z.string().default('app.trendpulse.local'),
    BASE_URL: z.url().optional(),
    VERIFY_EMAIL_PATH: z.string().default('/auth/email/confirm'),
    SCHEMA_PATH: z.string(),
  })
  .transform((data) => ({
    ...data,
    BASE_URL: data.BASE_URL ?? `https://${data.FRONTEND_DOMAIN}`,
  }));

export type AppConfig = z.infer<typeof configSchema>;

export const loadConfig = {
  from: {
    env: (env: NodeJS.ProcessEnv): AppConfig => configSchema.parse(env),
  },
};
