/**
 * InvoiceDisplay — shows the crypto invoice after POST /billing/invoice succeeds.
 *
 * Displays: order_id, amount, currency, payment_url (clickable link).
 * INVARIANT: No Stripe. No amounts from localStorage/URL. Taken from InvoiceResponse.
 * INVARIANT: Never log the payment_url — it may contain session tokens.
 */

import * as React from 'react';
import type { InvoiceResponse } from '../api';

interface InvoiceDisplayProps {
  invoice: InvoiceResponse;
}

export const InvoiceDisplay: React.FC<InvoiceDisplayProps> = ({ invoice }) => {
  return (
    <div
      data-testid="invoice-display"
      className="flex flex-col gap-4 rounded-2xl border border-amber-400/50 bg-amber-50/60 dark:bg-amber-900/20 p-6"
    >
      <div className="flex flex-col gap-1">
        <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
          Invoice created
        </span>
        <h2 className="m-0 text-xl font-bold">Pay to upgrade</h2>
        <p className="m-0 text-sm text-muted-foreground">
          Send crypto to complete your upgrade. The plan will activate after payment is confirmed.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-xl border border-border bg-background p-4">
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted-foreground">Amount</span>
          <span
            className="font-mono text-lg font-semibold"
            data-testid="invoice-amount"
          >
            {invoice.amount} {invoice.currency.toUpperCase()}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted-foreground">Order ID</span>
          <span
            className="font-mono text-xs text-muted-foreground break-all"
            data-testid="invoice-order-id"
          >
            {invoice.order_id}
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-sm text-muted-foreground">
          Status:{' '}
          <span className="font-medium text-amber-700 dark:text-amber-400">
            Awaiting payment
          </span>
        </span>
        <a
          href={invoice.payment_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-amber-500 px-6 text-sm font-medium text-white shadow-sm hover:bg-amber-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 transition-colors"
          data-testid="invoice-pay-link"
          aria-label="Open NOWPayments to complete your payment"
        >
          Pay now (crypto)
          <svg
            aria-hidden="true"
            width="12"
            height="12"
            viewBox="0 0 12 12"
            fill="none"
            className="shrink-0"
          >
            <path
              d="M2.5 2.5h7m0 0v7m0-7L2 10"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </a>
      </div>
    </div>
  );
};
