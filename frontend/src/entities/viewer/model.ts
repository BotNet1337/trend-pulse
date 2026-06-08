export type Theme = 'dark' | 'light' | 'system';

export type AlertType = 'success' | 'error';

export interface AlertItem {
  id: string;
  type: AlertType;
  title: string;
  description?: string;
}