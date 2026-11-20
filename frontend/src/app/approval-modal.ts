import { AfterViewInit, Component, ElementRef, input, output, viewChild } from '@angular/core';
import { DatePipe, JsonPipe } from '@angular/common';
import { Answer } from './api';
import { SqlDisplay } from './sql-display';

@Component({
  selector: 'approval-modal', imports: [SqlDisplay, DatePipe, JsonPipe],
  template: `
    <dialog #dialog aria-labelledby="review-title" (cancel)="escape($event)">
      <h2 id="review-title">{{ answer().change ? 'Review proposed change' : 'Review this query' }}</h2>
      @if (answer().change; as change) {
        <p><strong>{{ change.operation }}</strong> on <code>{{ change.target_table }}</code> ·
          {{ change.affected_count }} affected {{ change.affected_count === 1 ? 'row' : 'rows' }}</p>
        <small>Expires at {{ change.expires_at * 1000 | date:'mediumTime' }} (local time)</small>
      } @else { <p>{{ answer().message }} Approving runs the displayed SQL with read-only access.</p> }
      <sql-display [sql]="answer().sql" />
      @if (answer().change; as change) {
        <h3>Bound values</h3>
        <pre class="bindings">{{ change.parameters | json }}</pre>
        @for (row of (change.before.length ? change.before : change.after); track $index; let i = $index) {
          <table class="change-rows">
            <caption>Row {{ i + 1 }} of {{ change.affected_count }}</caption>
            <thead><tr><th>Column</th>
              @if (change.operation !== 'INSERT') { <th>{{ change.operation === 'DELETE' ? 'To be removed' : 'Before' }}</th> }
              @if (change.operation !== 'DELETE') { <th>{{ change.operation === 'INSERT' ? 'Proposed value' : 'After' }}</th> }
            </tr></thead>
            <tbody>@for (key of keys(row); track key) {
              <tr><th scope="row">{{ key }}</th>
                @if (change.operation !== 'INSERT') { <td>{{ change.before[i][key] | json }}</td> }
                @if (change.operation !== 'DELETE') { <td [class.modified]="change.operation === 'UPDATE' && change.before[i][key] !== change.after[i][key]">{{ change.after[i][key] | json }}</td> }
              </tr>
            }</tbody>
          </table>
        }
      }
      @if (error()) { <p role="alert">{{ error() }}</p> }
      <footer><button autofocus [disabled]="busy()" (click)="decision.emit('cancel')">Cancel</button>
        <button class="primary" [disabled]="busy()" (click)="decision.emit('approve')">{{ answer().change ? 'Approve change' : 'Approve query' }}</button></footer>
    </dialog>`,
})
export class ApprovalModal implements AfterViewInit {
  readonly keys = Object.keys;
  answer = input.required<Answer>();
  busy = input.required<boolean>();
  error = input('');
  decision = output<'approve' | 'cancel'>();
  dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');
  ngAfterViewInit() { this.dialog().nativeElement.showModal(); }
  escape(event: Event) {
    event.preventDefault();
    if (!this.busy()) this.decision.emit('cancel');
  }
}
