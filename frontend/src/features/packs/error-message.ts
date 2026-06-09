/**
 * extractErrorMessage — maps an axios-style error to a localised user-facing string.
 *
 * Shared between PacksBlock (component) and packs-api.spec.ts (unit test) so that
 * the logic lives in one place and tests are not tautological copies of the source.
 */

/** Extract a user-friendly error message from an axios-style error. */
export function extractErrorMessage(error: unknown): string {
  if (error && typeof error === 'object') {
    const e = error as { response?: { status?: number; data?: { detail?: string } } };
    if (e.response?.status === 402) {
      const detail = e.response?.data?.detail;
      return detail
        ? `Лимит паков: ${detail}`
        : 'Вы достигли лимита паков на текущем тарифе. Обновите план, чтобы добавить больше.';
    }
    if (e.response?.status === 404) {
      return 'Набор не найден.';
    }
  }
  return 'Что-то пошло не так. Попробуйте ещё раз.';
}
