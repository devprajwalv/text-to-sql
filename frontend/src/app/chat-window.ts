import { Component, ElementRef, inject, signal, viewChild } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Api, Answer } from './api';
import { ApprovalModal } from './approval-modal';
import { ResultsTable } from './results-table';
import { SqlDisplay } from './sql-display';

@Component({
  selector: 'chat-window', imports: [ApprovalModal, ResultsTable, SqlDisplay],
  templateUrl: './chat-window.html',
})
export class ChatWindow {
  private api = inject(Api);
  inputBox = viewChild.required<ElementRef<HTMLTextAreaElement>>('questionBox');
  text = signal('');
  review = signal(false);
  intent = signal<'read' | 'change'>('read');
  busy = signal(false);
  error = signal('');
  answers = signal<Answer[]>([]);
  pending = signal<Answer | null>(null);
  suggestions = [
    { type: 'Volume', icon: 'orders', question: 'How many distinct orders were placed?' },
    { type: 'Revenue', icon: 'revenue', question: 'What was the total merchandise revenue in BRL?' },
    { type: 'Geography', icon: 'states', question: 'Which customer state had the most distinct orders?' },
  ];

  choose(question: string) {
    this.intent.set('read');
    this.text.set(question);
    this.inputBox().nativeElement.focus();
  }

  async submit(event: Event) {
    event.preventDefault();
    const question = this.text().trim();
    if (!question || this.busy() || this.pending()) return;
    this.error.set('');
    this.busy.set(true);
    try {
      const answer = await this.api.ask(question, this.review(), this.intent());
      this.answers.update(items => [answer, ...items]);
      if (answer.status === 'pending') this.pending.set(answer);
      if (answer.status === 'completed') this.text.set('');
    } catch {
      this.error.set('Could not reach the query service. Check that FastAPI is running and retry.');
    } finally { this.busy.set(false); }
  }

  async decide(decision: 'approve' | 'cancel') {
    const pending = this.pending();
    if (!pending || this.busy()) return;
    this.error.set('');
    this.busy.set(true);
    try {
      const answer = await this.api.decide(pending.request_id, decision);
      this.answers.update(items => items.map(item => item.request_id === answer.request_id ? answer : item));
      this.pending.set(null);
      if (answer.status === 'completed') this.text.set('');
    } catch (e) {
      if (e && typeof e === 'object' && 'status' in e && e.status === 409) {
        this.pending.set(null);
        this.answers.update(items => items.map(item => item.request_id === pending.request_id
          ? { ...item, status: 'error', message: 'This review was already resolved. Submit a new question.' } : item));
      } else if (e instanceof HttpErrorResponse && e.status === 503 && typeof e.error?.detail === 'string') {
        this.error.set(e.error.detail);
      } else { this.error.set('The review service could not be reached. Retry your decision.'); }
    } finally { this.busy.set(false); }
  }
}
