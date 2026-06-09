/**
 * Delivery-config model — React Query hooks (TASK-017 AC2/AC4/AC5).
 *
 * useDeliveryConfig: GET /users/me/delivery-config
 * useUpdateDeliveryConfig: PATCH /users/me/delivery-config
 *
 * Client-side webhook validation (https + not localhost) is UX-only.
 * Server-side SSRF guard (task-009) is the authoritative enforcement.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { v4 as uuidv4 } from 'uuid';

import { useAlertStore } from '@/app/providers/use-alert-store';

import {
  deliveryConfigPath,
  getDeliveryConfig,
  updateDeliveryConfig,
  type DeliveryConfigRead,
  type DeliveryConfigUpdate,
} from './api';

export type { DeliveryConfigRead, DeliveryConfigUpdate };

const deliveryConfigQueryKey = [deliveryConfigPath] as const;

/** Fetch the current user's delivery configuration. */
export const useDeliveryConfig = () => {
  return useQuery<DeliveryConfigRead>({
    queryKey: deliveryConfigQueryKey,
    queryFn: () => getDeliveryConfig(),
  });
};

export interface UseUpdateDeliveryConfigOptions {
  onSuccess?: (data: DeliveryConfigRead) => void;
  onError?: (error: Error) => void;
}

/** PATCH /users/me/delivery-config — partial update. */
export const useUpdateDeliveryConfig = (
  options: UseUpdateDeliveryConfigOptions = {},
) => {
  const queryClient = useQueryClient();
  const alertStore = useAlertStore();
  const addAlert = alertStore((state) => state.add);

  return useMutation<DeliveryConfigRead, Error, DeliveryConfigUpdate>({
    mutationFn: (body) => updateDeliveryConfig(body),
    onSuccess: (data) => {
      // Update cache — keeps the UI in sync without a refetch
      queryClient.setQueryData(deliveryConfigQueryKey, data);
      addAlert({
        id: uuidv4(),
        type: 'success',
        title: 'Delivery settings saved',
        description: 'Your notification delivery settings were updated.',
      });
      options.onSuccess?.(data);
    },
    onError: (error) => {
      addAlert({
        id: uuidv4(),
        type: 'error',
        title: 'Failed to save delivery settings',
        description: error instanceof Error ? error.message : 'Unknown error',
      });
      options.onError?.(error);
    },
  });
};

/**
 * Client-side UX webhook validation (NOT a security guard — server does SSRF check).
 * Returns an error message string, or null if the URL looks OK from the client side.
 *
 * Rules:
 * - Must be https://
 * - Must not be localhost or 127.0.0.1 (or [::1])
 * - Must not be an RFC1918 private range (10.x, 172.16-31.x, 192.168.x — simple prefix check)
 *
 * Note: server-side SSRF guard (task-009) is the authoritative enforcement.
 * This function only prevents obvious mistakes early for better UX.
 */
export const validateWebhookUrlClient = (url: string): string | null => {
  if (!url) return null;

  if (!url.startsWith('https://')) {
    return 'Webhook URL must use HTTPS.';
  }

  let hostname: string;
  try {
    hostname = new URL(url).hostname.toLowerCase();
  } catch {
    return 'Invalid URL format.';
  }

  const PRIVATE_PREFIXES = [
    'localhost',
    '127.',
    '::1',
    '10.',
    '192.168.',
    '169.254.',
  ];
  // 172.16.0.0/12 — 172.16.x.x through 172.31.x.x
  const is172Private = /^172\.(1[6-9]|2\d|3[01])\./.test(hostname);

  const isPrivate =
    PRIVATE_PREFIXES.some((p) => hostname.startsWith(p)) || is172Private;

  if (isPrivate) {
    return 'Webhook URL must be a public HTTPS address (private/localhost addresses are not allowed).';
  }

  return null;
};
