import { TestBed } from '@angular/core/testing';
import { Api } from './api';
import { App } from './app';

describe('Query Studio', () => {
  it('opens the workspace and switches to the schema returned by the API', async () => {
    TestBed.configureTestingModule({
      imports: [App],
      providers: [{ provide: Api, useValue: {
        health: async () => ({ dataset_loaded: true, retrieval_mode: 'full_schema', key_configured: false }),
        schema: async () => [{ table_name: 'fact_orders', columns: [], joins: [], description: 'One row per item' }],
      } }],
    });
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('h1')?.textContent).toBe('Query workspace');
    host.querySelector<HTMLButtonElement>('.outline')!.click();
    await fixture.whenStable();
    expect(host.querySelector('schema-explorer')?.textContent).toContain('fact_orders');
  });
});
