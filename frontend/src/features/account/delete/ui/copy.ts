/**
 * Delete-account dialog copy (TASK-072 AC4).
 *
 * Отражает реальный каскад удаления: `DELETE /account` →
 * `compliance.account.delete_user` сносит пользователя и все зависимые строки
 * через ON DELETE CASCADE (watchlists, alerts history, subscription).
 * Вынесено в константу, чтобы unit-тест ассертил копию без рендера компонента
 * (vitest здесь — node env, без testing-library).
 */
export const DELETE_ACCOUNT_DESCRIPTION =
  'Removes your account, your watchlists, alerts history and subscription. ' +
  'This cannot be undone.';
