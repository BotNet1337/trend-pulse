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
    <div data-testid="invoice-display" className="fs-card invoice-card">
      <div>
        <span className="invoice-eyebrow">Invoice created</span>
        <h2>Pay to upgrade</h2>
        <p className="lede">
          Send crypto to complete your upgrade. The plan will activate after payment is confirmed.
        </p>
      </div>

      <dl className="invoice-facts">
        <div>
          <dt>Amount</dt>
          <dd className="invoice-amount" data-testid="invoice-amount">
            {invoice.amount} {invoice.currency.toUpperCase()}
          </dd>
        </div>
        <div>
          <dt>Order ID</dt>
          <dd className="invoice-order" data-testid="invoice-order-id">
            {invoice.order_id}
          </dd>
        </div>
      </dl>

      <div className="invoice-actions">
        <a
          href={invoice.payment_url}
          target="_blank"
          rel="noopener noreferrer"
          className="fs-btn fs-btn--primary"
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
        <span className="invoice-status">
          Status: <strong>Awaiting payment</strong>
        </span>
      </div>
    </div>
  );
};
