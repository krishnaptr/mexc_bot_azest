export interface BotStats {
  status: string;
  is_active: boolean;
  active_trade: boolean;
  total_trades: number;
  win_rate: number;
  equity: number;
  total_net_pnl_percent: number;
  dry_run: boolean;
  position: any;
}

export interface TradeRecord {
  id?: number;
  symbol: string;
  side: string;
  net_pnl: number;
  timestamp?: string;
}

export interface ChartResponse {
  status: string;
  labels: string[];
  cumulative_pnl: number[];
}
