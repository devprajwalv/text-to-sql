import { Component, inject, signal } from '@angular/core';
import { Api, Health, Table } from './api';
import { ChatWindow } from './chat-window';
import { SchemaExplorer } from './schema-explorer';

@Component({
  imports: [ChatWindow, SchemaExplorer],
  selector: 'app-root',
  templateUrl: './app.html',
})
export class App {
  private api = inject(Api);
  page = signal<'query' | 'schema'>('query');
  health = signal<Health | null>(null);
  tables = signal<Table[]>([]);
  loading = signal(true);
  error = signal(false);

  constructor() { void this.connect(); }

  async connect() {
    this.loading.set(true);
    this.error.set(false);
    try {
      const [health, tables] = await Promise.all([this.api.health(), this.api.schema()]);
      this.health.set(health);
      this.tables.set(tables);
    } catch {
      this.error.set(true);
    } finally { this.loading.set(false); }
  }
}
