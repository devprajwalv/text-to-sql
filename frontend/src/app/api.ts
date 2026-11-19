import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

export interface Table {
  table_name: string;
  description: string;
  columns: { name: string; type: string; description: string }[];
  joins: string[];
}

export interface Answer {
  request_id: string;
  question: string;
  sql: string;
  status: 'completed' | 'pending' | 'cancelled' | 'blocked' | 'error';
  message: string;
  columns: string[];
  results: (string | number | null)[][];
  relevant_tables: string[];
  retrieval_mode: string;
  latency_ms: number;
  truncated: boolean;
}

export interface Health {
  key_configured: boolean;
  dataset_loaded: boolean;
  retrieval_mode: string;
}

@Injectable({ providedIn: 'root' })
export class Api {
  private http = inject(HttpClient);
  health() { return firstValueFrom(this.http.get<Health>('/api/health')); }
  schema() { return firstValueFrom(this.http.get<Table[]>('/api/schema')); }
  ask(question: string, review: boolean) {
    return firstValueFrom(this.http.post<Answer>('/api/query', { question, review }));
  }
  decide(request_id: string, decision: 'approve' | 'cancel') {
    return firstValueFrom(this.http.post<Answer>('/api/approve', { request_id, decision }));
  }
}
