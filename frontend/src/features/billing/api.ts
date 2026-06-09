/**
 * Billing API — POST /billing/invoice (NOWPayments, TASK-017).
 *
 * INVARIANT: NO Stripe. Only NOWPayments via POST /billing/invoice.
 * Cookie-auth (httpOnly); no tokens in localStorage/URL/logs.
 */

import type { AxiosInstance } from 'axios';

import { apiClient } from '@/shared/api';
import type { components } from '@/shared/api/gen.types';

export type InvoiceRequest = components['schemas']['InvoiceRequest'];
export type InvoiceResponse = components['schemas']['InvoiceResponse'];
export type Plan = components['schemas']['Plan'];
export type BillingPeriod = components['schemas']['BillingPeriod'];

export const createInvoicePath = '/billing/invoice' as const;

/**
 * POST /billing/invoice — create a NOWPayments crypto invoice for plan upgrade.
 * Returns `InvoiceResponse` with payment_url (crypto), order_id, amount, currency.
 * Returns `InvoiceResponse` on success; throws AxiosError with friendly message on failure.
 */
export const createInvoice = async (
  body: InvoiceRequest,
  client?: AxiosInstance,
): Promise<InvoiceResponse> => {
  const executor = client ?? apiClient;
  const response = await executor.post<InvoiceResponse>(createInvoicePath, body);
  return response.data;
};
