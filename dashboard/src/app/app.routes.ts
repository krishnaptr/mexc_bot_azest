import { Routes } from '@angular/router';
import { Layout } from './layout/layout';
import { Dashboard } from './pages/dashboard/dashboard';
import { History } from './pages/history/history';
import { Settings } from './pages/settings/settings';
export const routes: Routes = [
  {
    path: '',
    component: Layout,
    children: [
      { path: '', component: Dashboard },
      { path: 'history', component: History },
      { path: 'settings', component: Settings },
    ]
  }
];
