// TASARIM.md §9 — backend'in (Faz 6, `uvicorn app.main:app`) varsayılan adresi.
// Tek-operatörlük bir demo/izleme sistemi (§0.2) olduğu için ayrı bir
// prod/staging environment dosyası YOK — İlke 8 (basitlik önceliği).
export const environment = {
  apiBaseUrl: 'http://localhost:8000',
  wsUrl: 'ws://localhost:8000/ws/live',
};
