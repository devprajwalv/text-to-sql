import { AfterViewInit, Component, ElementRef, input, output, viewChild } from '@angular/core';
import { Answer } from './api';
import { SqlDisplay } from './sql-display';

@Component({
  selector: 'approval-modal', imports: [SqlDisplay],
  template: `
    <dialog #dialog aria-labelledby="review-title" (cancel)="escape($event)">
      <h2 id="review-title">Review this query</h2>
      <p>{{ answer().message }} Approving runs the displayed SQL with read-only access.</p>
      <sql-display [sql]="answer().sql" />
      @if (error()) { <p role="alert">{{ error() }}</p> }
      <footer><button autofocus [disabled]="busy()" (click)="decision.emit('cancel')">Cancel</button>
        <button class="primary" [disabled]="busy()" (click)="decision.emit('approve')">Approve query</button></footer>
    </dialog>`,
})
export class ApprovalModal implements AfterViewInit {
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
