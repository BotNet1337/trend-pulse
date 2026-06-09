/**
 * Billing feature model — React Query hooks for invoice creation (TASK-017).
 *
 * INVARIANT: No Stripe. Invoice created via POST /billing/invoice (NOWPayments).
 * On success the UI displays the invoice (amount, currency, payment_url, order_id).
 * The user's plan is polled via GET /users/me (existing useCurrentUser hook) to
 * detect the IPN-triggered upgrade without a dedicated WS connection.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { v4 as uuidv4 } from 'uuid';

import { useAlertStore } from '@/app/providers/use-alert-store';

import { createInvoice, type InvoiceRequest, type InvoiceResponse } from './api';

export type { InvoiceRequest, InvoiceResponse };

const CREATE_INVOICE_MUTATION_KEY = ['billing', 'create-invoice'];

export interface UseCreateInvoiceOptions {
  onSuccess?: (invoice: InvoiceResponse) => void;
  onError?: (error: Error) => void;
}

/**
 * useMutation wrapper for POST /billing/invoice.
 * On error, an alert is added to the global alert store.
 */
export const useCreateInvoice = (options: UseCreateInvoiceOptions = {}) => {
  const queryClient = useQueryClient();
  const alertStore = useAlertStore();
  const addAlert = alertStore((state) => state.add);

  return useMutation<InvoiceResponse, Error, InvoiceRequest>({
    mutationKey: CREATE_INVOICE_MUTATION_KEY,
    mutationFn: (body) => createInvoice(body),
    onSuccess: (invoice) => {
      // Invalidate the /users/me query so plan polling picks up any immediate changes
      void queryClient.invalidateQueries({ queryKey: ['/users/me'] });
      options.onSuccess?.(invoice);
    },
    onError: (error) => {
      addAlert({
        id: uuidv4(),
        type: 'error',
        title: 'Invoice creation failed',
        description: error instanceof Error ? error.message : 'Unknown error',
      });
      options.onError?.(error);
    },
  });
};
