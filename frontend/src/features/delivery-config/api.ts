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
import type { components } from '@/shared/api/gen.types';

export const deliveryConfigPath = '/users/me/delivery-config' as const;

/**
 * Backend GET response. `telegram_bot_token_masked` is "***<last4>" or null —
 * the full token is NEVER returned (write-mostly). Sourced from gen.types
 * (single source of truth for the API contract).
 */
export type DeliveryConfigRead = components['schemas']['DeliveryConfigRead'];

/** PATCH request body (partial update; explicit null clears chat_id/webhook_url). */
export type DeliveryConfigUpdate = components['schemas']['DeliveryConfigUpdate'];

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
