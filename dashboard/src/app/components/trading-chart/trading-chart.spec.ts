import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TradingChart } from './trading-chart';

describe('TradingChart', () => {
  let component: TradingChart;
  let fixture: ComponentFixture<TradingChart>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TradingChart]
    })
    .compileComponents();

    fixture = TestBed.createComponent(TradingChart);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
