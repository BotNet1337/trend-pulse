import { z } from 'zod';

const configSchema = z.object({
  PORT: z.coerce.number().default(4000),
  NODE_ENV: z.string().default('development'),
  API_URL: z.string().url(),

  COOKIE_SECRET: z.string().min(16),
});

export type AppConfig = z.infer<typeof configSchema>;

export const loadConfig = {
  from: {
    env: (env: unknown) => {
      const parsed = configSchema.parse(env);

      const apiUrl = new URL(parsed.API_URL);
      if (apiUrl.hostname === 'localhost') {
        apiUrl.hostname = '127.0.0.1';
      }

      return {
        ...parsed,
        API_URL: apiUrl.toString().replace(/\/$/, ''),
      };
    },
  },
};
