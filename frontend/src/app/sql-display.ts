import { Component, input, signal } from '@angular/core';

@Component({
  selector: 'sql-display',
  template: `
    <section class="sql"><header><h3>Generated SQL</h3>
      <button type="button" (click)="copy()">{{ feedback() }}</button></header>
      <pre><code>{{ sql() }}</code></pre>
    </section>`,
})
export class SqlDisplay {
  sql = input.required<string>();
  feedback = signal('Copy SQL');
  async copy() {
    try {
      await navigator.clipboard.writeText(this.sql());
      this.feedback.set('Copied');
    } catch {
      this.feedback.set('Select SQL to copy');
    }
  }
}
