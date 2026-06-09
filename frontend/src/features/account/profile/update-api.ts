/**
 * Profile update — placeholder for TrendPulse C2+.
 * The backend does not yet expose a profile update endpoint in C1.
 * This module is kept as a stub so downstream imports compile without errors.
 */

export interface UpdateUserProfileParams {
  userId: string
  name: string
}

export const updateUserProfilePath = "/users/me/profile" as const
