import { Injectable, signal } from '@angular/core';
import { Subject } from 'rxjs';

import { environment } from '../../../environments/environment';
import { LiveEvent } from '../models/simulation.model';

const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30_000;

/** Native WebSocket + reconnect/backoff — TASARIM.md §9, §8: "WS
 * /ws/live'a bağlanır → gelen olaylarla ekranı delta günceller.
 * Bağlantı koparsa: reconnect...". Bu servis KASITLI OLARAK "ne
 * yapılacağını" bilmez (state güncellemesi/backfill mantığı
 * simulation-state.service.ts'e ve decision-log gibi component'lere
 * aittir) — tek işi bağlantıyı canlı tutmak ve gelen mesajları
 * yayınlamaktır (İlke: tek sorumluluk). */
@Injectable({ providedIn: 'root' })
export class WsService {
  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private backoffMs = INITIAL_BACKOFF_MS;
  private manuallyClosed = false;

  private readonly _connected = signal(false);
  readonly connected = this._connected.asReadonly();

  private readonly eventsSubject = new Subject<LiveEvent>();
  readonly events$ = this.eventsSubject.asObservable();

  connect(): void {
    this.manuallyClosed = false;
    this.openSocket();
  }

  disconnect(): void {
    this.manuallyClosed = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
    this.socket = null;
    this._connected.set(false);
  }

  private openSocket(): void {
    const socket = new WebSocket(environment.wsUrl);
    this.socket = socket;

    socket.onopen = () => {
      this._connected.set(true);
      this.backoffMs = INITIAL_BACKOFF_MS;
    };

    socket.onmessage = (message: MessageEvent<string>) => {
      try {
        const event = JSON.parse(message.data) as LiveEvent;
        this.eventsSubject.next(event);
      } catch {
        // Sunucu her zaman geçerli JSON gönderir (bkz. ws/manager.py);
        // bozuk bir mesaj yalnızca ağ katmanında bir bozulma anlamına
        // gelir — sessizce yok say, bağlantıyı KOPARMA.
      }
    };

    socket.onclose = () => {
      this._connected.set(false);
      this.socket = null;
      if (!this.manuallyClosed) {
        this.scheduleReconnect();
      }
    };

    socket.onerror = () => {
      socket.close();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) {
      return;
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, this.backoffMs);
    this.backoffMs = Math.min(MAX_BACKOFF_MS, this.backoffMs * 2);
  }
}
