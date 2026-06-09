/**
 * Delivery-config API — GET/PATCH /users/me/delivery-config (TASK-017 AC2/AC4/AC5).
 *
 * INVARIANT: telegram_bot_token is write-mostly — the backend returns only a masked
 * value (last 4 chars). Never store or log the full token.
 * INVARIANT: No delivery secrets in localStorage / URL / bundle.
 * Cookie-auth (httpOnly fastapiusersauth).
 */

import type { AxiosInstance } from 'axios';
import { apiClient } from '@/shared/api';

export const deliveryConfigPath = '/users/me/delivery-config' as const;

/** Backend GET /users/me/delivery-config response. */
export interface DeliveryConfigRead {
  /** Masked bot token: "***<last4>" or null if not set. Full token is NEVER returned. */
  telegram_bot_token_masked: string | null;
  telegram_chat_id: string | null;
  webhook_url: string | null;
}

/** PATCH /users/me/delivery-config request body. All fields optional (partial update). */
export interface DeliveryConfigUpdate {
  /** Write-only: sets the bot token. Not echoed back. Send null to no-op. */
  telegram_bot_token?: string | null;
  telegram_chat_id?: string | null;
  /** Requires Pro+ plan (feature-gate: 403 on Free). SSRF-validated server-side. */
  webhook_url?: string | null;
}

export const getDeliveryConfig = async (
  client?: AxiosInstance,
): Promise<DeliveryConfigRead> => {
  const executor = client ?? apiClient;
  const response = await executor.get<DeliveryConfigRead>(deliveryConfigPath);
  return response.data;
};

export const updateDeliveryConfig = async (
  body: DeliveryConfigUpdate,
  client?: AxiosInstance,
): Promise<DeliveryConfigRead> => {
  const executor = client ?? apiClient;
  const response = await executor.patch<DeliveryConfigRead>(deliveryConfigPath, body);
  return response.data;
};
