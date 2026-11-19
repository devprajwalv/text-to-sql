import { TestBed } from '@angular/core/testing';
import { ResultsTable } from './results-table';

describe('ResultsTable', () => {
  it('pages through ordered rows and retains empty result headers', async () => {
    const fixture = TestBed.createComponent(ResultsTable);
    const host = fixture.nativeElement as HTMLElement;
    const page = { columns: ['order_id'], results: Array.from({ length: 12 }, (_, i) => [i]), truncated: false };
    fixture.componentRef.setInput('answer', page);
    await fixture.whenStable();
    expect(host.querySelectorAll('tbody tr')).toHaveLength(10);
    host.querySelectorAll<HTMLButtonElement>('button')[1].click();
    await fixture.whenStable();
    expect(host.querySelectorAll('tbody tr')).toHaveLength(2);
    expect(host.querySelector('tbody td')?.textContent).toBe('10');

    fixture.componentRef.setInput('answer', { ...page, results: [] });
    await fixture.whenStable();
    expect(host.textContent).toContain('No matching rows');
    expect(host.querySelector('th')?.textContent).toBe('order_id');
  });
});
