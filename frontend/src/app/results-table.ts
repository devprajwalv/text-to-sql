import { Component, computed, input, signal } from '@angular/core';
import { Answer } from './api';

@Component({
  selector: 'results-table',
  template: `
    <section class="results"><header><h3>Results</h3>
      <span>{{ answer().results.length }} rows{{ answer().truncated ? ' · capped at 200' : '' }}</span></header>
      @if (answer().results.length === 0) { <p>No matching rows.</p> }
      <div class="table-scroll" tabindex="0" aria-label="Query result table"><table>
        <thead><tr>@for (col of answer().columns; track $index) { <th>{{ col }}</th> }</tr></thead>
        <tbody>@for (row of visible(); track $index) {
          <tr>@for (cell of row; track $index) { <td>{{ cell ?? 'NULL' }}</td> }</tr>
        }</tbody>
      </table></div>
      @if (pages() > 1) {
        <footer><button (click)="page.set(page() - 1)" [disabled]="page() === 0">Previous</button>
          <span>Page {{ page() + 1 }} of {{ pages() }}</span>
          <button (click)="page.set(page() + 1)" [disabled]="page() + 1 >= pages()">Next</button></footer>
      }
    </section>`,
})
export class ResultsTable {
  answer = input.required<Answer>();
  page = signal(0);
  pages = computed(() => Math.ceil(this.answer().results.length / 10));
  visible = computed(() => this.answer().results.slice(this.page() * 10, (this.page() + 1) * 10));
}
