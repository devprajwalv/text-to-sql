import { Component, computed, input, signal } from '@angular/core';
import { Table } from './api';

@Component({
  selector: 'schema-explorer',
  template: `
    <h1>Schema explorer</h1><p class="intro">Explore the tables, columns, and join keys behind your queries.</p>
    <label class="search">Filter tables or columns
      <input type="search" [value]="term()" (input)="term.set($any($event.target).value)" placeholder="Search by name" />
    </label>
    <div class="schema-list">@for (table of filtered(); track table.table_name) {
      <details><summary><strong>{{ table.table_name }}</strong><span>{{ table.columns.length }} columns</span></summary>
        <p>{{ table.description }}</p><dl>@for (col of table.columns; track col.name) {
          <dt>{{ col.name }} <small>{{ col.type }}</small></dt><dd>{{ col.description }}</dd>
        }</dl>
        @for (join of table.joins; track join) { <p><code>{{ join }}</code></p> }
      </details>
    } @empty { <p>No matching tables.</p> }</div>`,
})
export class SchemaExplorer {
  tables = input.required<Table[]>();
  term = signal('');
  filtered = computed(() => {
    const key = this.term().trim().toLowerCase();
    return this.tables().filter(t => [t.table_name, ...t.columns.map(c => c.name)].some(n => n.includes(key)));
  });
}
