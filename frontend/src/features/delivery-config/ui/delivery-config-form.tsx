/**
 * DeliveryConfigForm — edit Telegram bot token, chat_id, webhook_url (TASK-017).
 *
 * Security invariants:
 * - Bot token input is password type; value is NOT shown after save (masked by backend).
 * - Webhook URL has client-side UX validation (https + public host) — server is authoritative.
 * - No delivery secrets are stored in localStorage/URL/logs.
 * - On Pro plan, webhook_url field is visible. On Free plan, an upsell is shown.
 */

import * as React from 'react';

import { PLAN_PRO, type PlanId, isPlanAtLeast } from '@/entities/plan';
import { Button } from '@/shared/components/button';
import { Input } from '@/shared/components/input';
import { Label } from '@/shared/components/label';
import { Spinner } from '@/shared/components/spinner';

import { validateWebhookUrlClient } from '../model';
import type { DeliveryConfigRead, DeliveryConfigUpdate } from '../api';

interface DeliveryConfigFormProps {
  /** Current values from GET /users/me/delivery-config. */
  current: DeliveryConfigRead;
  /** User's plan from GET /users/me — used to show/hide webhook field. */
  currentPlan: PlanId;
  /** Called when the form is submitted. Returns a promise. */
  onSave: (data: DeliveryConfigUpdate) => Promise<void>;
  /** True while the PATCH request is in-flight. */
  isSaving?: boolean;
}

export const DeliveryConfigForm: React.FC<DeliveryConfigFormProps> = ({
  current,
  currentPlan,
  onSave,
  isSaving = false,
}) => {
  const [botToken, setBotToken] = React.useState('');
  const [chatId, setChatId] = React.useState(current.telegram_chat_id ?? '');
  const [webhookUrl, setWebhookUrl] = React.useState(current.webhook_url ?? '');
  const [webhookError, setWebhookError] = React.useState<string | null>(null);

  const hasPro = isPlanAtLeast(currentPlan, PLAN_PRO);

  // Sync chatId/webhookUrl if parent data changes (e.g. after a save)
  React.useEffect(() => {
    setChatId(current.telegram_chat_id ?? '');
    setWebhookUrl(current.webhook_url ?? '');
  }, [current.telegram_chat_id, current.webhook_url]);

  const handleWebhookChange = (value: string) => {
    setWebhookUrl(value);
    if (value) {
      setWebhookError(validateWebhookUrlClient(value));
    } else {
      setWebhookError(null);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Client-side UX validation for webhook URL
    if (webhookUrl) {
      const err = validateWebhookUrlClient(webhookUrl);
      if (err) {
        setWebhookError(err);
        return;
      }
    }

    const body: DeliveryConfigUpdate = {};
    if (botToken.trim()) {
      body.telegram_bot_token = botToken.trim();
    }
    if (chatId !== (current.telegram_chat_id ?? '')) {
      body.telegram_chat_id = chatId || null;
    }
    if (hasPro && webhookUrl !== (current.webhook_url ?? '')) {
      body.webhook_url = webhookUrl || null;
    }

    // Only call onSave if there are actual changes
    if (Object.keys(body).length === 0) return;

    await onSave(body);

    // Clear bot token field after save (write-only UX)
    setBotToken('');
  };

  return (
    <form
      data-testid="delivery-config-form"
      onSubmit={(e) => { void handleSubmit(e); }}
    >
      <div className="fs-form-section__body">
        {/* Telegram Bot Token (write-only) */}
        <div className="fs-field">
          <Label htmlFor="delivery-bot-token">Telegram bot token</Label>
          <Input
            id="delivery-bot-token"
            type="password"
            autoComplete="new-password"
            value={botToken}
            onChange={(e) => setBotToken(e.target.value)}
            placeholder={
              current.telegram_bot_token_masked
                ? current.telegram_bot_token_masked
                : 'Enter bot token'
            }
            disabled={isSaving}
            className="fs-input--mono"
            aria-label="Telegram bot token"
          />
          <p className="fs-hint">
            {current.telegram_bot_token_masked
              ? `Current: ${current.telegram_bot_token_masked} — enter a new value to change.`
              : 'Set a bot token to receive Telegram notifications.'}
          </p>
        </div>

        {/* Telegram Chat ID */}
        <div className="fs-field">
          <Label htmlFor="delivery-chat-id">Telegram chat ID</Label>
          <Input
            id="delivery-chat-id"
            type="text"
            value={chatId}
            onChange={(e) => setChatId(e.target.value)}
            placeholder="e.g. -100123456789"
            disabled={isSaving}
            className="fs-input--mono"
            aria-label="Telegram chat ID"
          />
          <p className="fs-hint">
            The Telegram chat or channel ID to send alerts to (e.g. -100123456789).
          </p>
        </div>

        {/* Webhook URL (Pro+ only) */}
        <div className="fs-field">
          <Label htmlFor="delivery-webhook-url">Webhook URL</Label>
          {hasPro ? (
            <>
              <Input
                id="delivery-webhook-url"
                type="url"
                value={webhookUrl}
                onChange={(e) => handleWebhookChange(e.target.value)}
                placeholder="https://your-server.com/webhook"
                disabled={isSaving}
                className="fs-input--mono"
                aria-label="Webhook URL"
                aria-invalid={webhookError !== null}
                aria-describedby={webhookError ? 'webhook-url-error' : undefined}
              />
              {webhookError && (
                <p
                  id="webhook-url-error"
                  role="alert"
                  className="fs-error"
                  data-testid="webhook-url-error"
                >
                  {webhookError}
                </p>
              )}
              <p className="fs-hint">
                POST alerts to a public HTTPS endpoint. Must not be a private/localhost address.
              </p>
            </>
          ) : (
            <>
              <div
                className="setting-row__value"
                aria-label="Webhook delivery requires Pro plan"
                data-testid="webhook-pro-upsell"
              >
                Upgrade to Pro to use webhooks
              </div>
              <p className="fs-hint">
                Webhook delivery is available on Pro and Team plans.
              </p>
            </>
          )}
        </div>
      </div>

      <div className="fs-form-section__foot">
        <Button
          type="submit"
          disabled={isSaving}
          data-testid="delivery-config-save"
          aria-label="Save delivery settings"
        >
          {isSaving ? (
            <>
              <Spinner className="mr-2" />
              Saving…
            </>
          ) : (
            'Save'
          )}
        </Button>
      </div>
    </form>
  );
};
