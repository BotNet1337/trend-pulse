/**
 * QrLoginDialog (TASK-117) — the "Add account" QR-login flow.
 *
 * Flow: open → POST start → render the `qr_url` as a scannable QR (QRCodeSVG) →
 * poll every ~2s → on success reveal the NEW session string in a copy-to-
 * clipboard field with the "add to TELEGRAM_POOL_SESSIONS in the vault and
 * redeploy" note. On timeout/password_needed/error the SPECIFIC reason is shown
 * (never a generic error) with a "Regenerate QR" action.
 *
 * SECURITY (invariant): `session_string` is a one-time secret. It is rendered
 * once, copied via the platform clipboard, and NEVER logged (no console.*), nor
 * persisted. React-Query's cache holds it only for the dialog's lifetime; the
 * poll query is removed on close so the secret does not linger.
 */

import React from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { useQueryClient } from '@tanstack/react-query';

import { Button } from '@/shared/components/button';
import { ModalDialog } from '@/shared/components/modal-dialog';
import { CheckCircle2, Copy, Loader2, RefreshCw } from '@/shared/images';
import { copyToClipboard } from '@/shared/lib';

import { useQrLoginPoll, useQrLoginStart, qrLoginPollQueryKey } from '../queries';
import { asQrLoginStatus, isTerminalQrStatus, qrStatusMessage } from '../lib';
import type { AxiosError } from 'axios';

interface QrLoginDialogProps {
  open: boolean;
  onClose: () => void;
}

const VAULT_NOTE =
  'Add this to TELEGRAM_POOL_SESSIONS in the vault and redeploy. It is shown only once.';

const COPY_FAILED_MESSAGE =
  'Copy failed — select the session string above and copy it manually.';

/** Friendly message for a failed `start` (503 unconfigured / 429 capacity / other). */
function startErrorMessage(error: AxiosError | null): string {
  const status = error?.response?.status;
  if (status === 503) return 'QR login is not configured on the server.';
  if (status === 429) return 'Too many concurrent QR logins in progress. Retry shortly.';
  return error?.message ?? 'Could not start QR login. Please try again.';
}

export const QrLoginDialog: React.FC<QrLoginDialogProps> = ({ open, onClose }) => {
  const queryClient = useQueryClient();
  const startMutation = useQrLoginStart();
  const [token, setToken] = React.useState<string | null>(null);
  const [qrUrl, setQrUrl] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);
  const [copyError, setCopyError] = React.useState<string | null>(null);

  const poll = useQrLoginPoll(token);
  const status = poll.data ? asQrLoginStatus(poll.data.status) : null;

  const begin = React.useCallback(() => {
    setCopied(false);
    setCopyError(null);
    startMutation.mutate(undefined, {
      onSuccess: (data) => {
        setToken(data.token);
        setQrUrl(data.qr_url);
      },
    });
  }, [startMutation]);

  // Start a login as soon as the dialog opens (once per open).
  React.useEffect(() => {
    if (open && token === null && !startMutation.isPending) {
      begin();
    }
    // begin/startMutation are stable enough; we intentionally key on `open`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const reset = React.useCallback(() => {
    if (token !== null) {
      queryClient.removeQueries({ queryKey: qrLoginPollQueryKey(token) });
    }
    setToken(null);
    setQrUrl(null);
    setCopied(false);
    setCopyError(null);
    startMutation.reset();
  }, [queryClient, startMutation, token]);

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      reset();
      onClose();
    }
  };

  const handleRegenerate = () => {
    reset();
    begin();
  };

  const sessionString =
    status === 'success' ? poll.data?.session_string ?? null : null;

  const handleCopy = async () => {
    if (!sessionString) return;
    const ok = await copyToClipboard(sessionString);
    if (ok) {
      setCopied(true);
      setCopyError(null);
    } else {
      setCopyError(COPY_FAILED_MESSAGE);
    }
  };

  const startError = startMutation.isError
    ? (startMutation.error as AxiosError)
    : null;
  const isStarting = startMutation.isPending || (token !== null && qrUrl === null);
  const isTerminal = status !== null && isTerminalQrStatus(status);

  return (
    <ModalDialog
      open={open}
      onOpenChange={handleOpenChange}
      width="confirm"
      title="Add a pool account"
      description="Scan the QR code with the Telegram app you want to add to the pool."
    >
      <div className="flex flex-col gap-4">
        {startError && (
          <p role="alert" className="m-0 text-sm text-destructive">
            {startErrorMessage(startError)}
          </p>
        )}

        {isStarting && !startError && (
          <p className="m-0 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Starting QR login…
          </p>
        )}

        {/* QR + live status while pending */}
        {qrUrl && status !== 'success' && (
          <div className="flex flex-col items-center gap-3">
            <div className="rounded-lg bg-white p-4">
              <QRCodeSVG value={qrUrl} size={200} marginSize={0} />
            </div>
            {status && (
              <p
                role="status"
                className="m-0 text-center text-sm text-muted-foreground"
                data-testid="qr-status"
              >
                {qrStatusMessage(status, poll.data?.reason ?? null)}
              </p>
            )}
          </div>
        )}

        {/* Success: reveal the one-time session string */}
        {status === 'success' && sessionString && (
          <div className="flex flex-col gap-3" data-testid="qr-success">
            <p className="m-0 flex items-center gap-2 text-sm font-medium">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              {qrStatusMessage('success', null)}
            </p>
            <div className="grid grid-cols-[1fr_auto] items-center gap-2">
              <code
                data-testid="qr-session-string"
                className="block min-w-0 select-all break-all rounded-md border border-border bg-secondary/40 px-3 py-2.5 font-mono text-xs"
              >
                {sessionString}
              </code>
              <Button
                type="button"
                variant="outline"
                className="h-11 min-w-24"
                onClick={() => void handleCopy()}
                data-testid="qr-copy"
              >
                {copied ? (
                  <>
                    <CheckCircle2 className="mr-1.5 h-4 w-4" />
                    Copied
                  </>
                ) : (
                  <>
                    <Copy className="mr-1.5 h-4 w-4" />
                    Copy
                  </>
                )}
              </Button>
            </div>
            {copyError && (
              <p role="alert" className="m-0 text-xs text-destructive">
                {copyError}
              </p>
            )}
            <p className="m-0 text-xs text-muted-foreground">{VAULT_NOTE}</p>
          </div>
        )}

        {/* Terminal failure (expired / password_needed / error): specific reason */}
        {isTerminal && status !== 'success' && (
          <p role="alert" className="m-0 text-sm text-destructive" data-testid="qr-terminal">
            {qrStatusMessage(status, poll.data?.reason ?? null)}
          </p>
        )}

        <div className="flex justify-end gap-2">
          {(isTerminal && status !== 'success') || startError ? (
            <Button type="button" variant="outline" onClick={handleRegenerate}>
              <RefreshCw className="mr-1.5 h-4 w-4" />
              Regenerate QR
            </Button>
          ) : null}
          <Button type="button" onClick={() => handleOpenChange(false)}>
            {status === 'success' ? "I've copied the session" : 'Close'}
          </Button>
        </div>
      </div>
    </ModalDialog>
  );
};
