import {
  Component,
  AfterViewInit,
  Input,
  OnChanges,
  SimpleChanges,
} from '@angular/core';
declare const TradingView: any;

@Component({
  selector: 'app-trading-chart',
  templateUrl: './trading-chart.html',
})
export class TradingChartComponent implements AfterViewInit, OnChanges {
  @Input() symbol: string = 'BTCUSDT';
  @Input() isDarkMode: boolean = true;

  ngAfterViewInit() {
    this.loadTradingViewScript();
  }

  ngOnChanges(changes: SimpleChanges) {
    if (
      (changes['symbol'] && !changes['symbol'].firstChange) ||
      (changes['isDarkMode'] && !changes['isDarkMode'].firstChange)
    ) {
      this.initChart();
    }
  }

  private loadTradingViewScript() {
    if (document.getElementById('tradingview-widget-script')) {
      this.initChart();
      return;
    }

    const script = document.createElement('script');
    script.id = 'tradingview-widget-script';
    script.src = 'https://s3.tradingview.com/tv.js';
    script.async = true;
    script.onload = () => this.initChart();
    document.head.appendChild(script);
  }

  private initChart() {
    if (typeof TradingView === 'undefined') return;
    const cleanSymbol = this.symbol.replace('_', '');

    new TradingView.widget({
      autosize: true,
      symbol: `MEXC:${cleanSymbol}`,
      interval: '15',
      timezone: 'Asia/Jakarta',
      theme: this.isDarkMode ? 'dark' : 'light',
      style: '1',
      locale: 'id',
      toolbar_bg: this.isDarkMode ? '#0f172a' : '#f8fafc',
      enable_publishing: false,
      hide_top_toolbar: false,
      hide_legend: false,
      save_image: false,
      container_id: 'tv_chart_container',
      backgroundColor: this.isDarkMode ? '#0f172a' : '#ffffff',
      gridColor: this.isDarkMode ? '#1e293b' : '#f1f5f9',
    });
  }
}
