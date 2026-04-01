"""
ADAM Progress Bus — in-memory pub/sub para eventos SSE de progreso.
Funciona con un solo worker uvicorn (deployment estándar).
Soporta múltiples conexiones SSE simultáneas por job_id.
"""
import asyncio

# job_id → lista de colas suscritas (una por conexión SSE activa)
_queues: dict[str, list[asyncio.Queue]] = {}


def subscribe(job_id: str) -> "asyncio.Queue[dict]":
    """Registra una nueva cola suscriptora para el job dado."""
    q: asyncio.Queue = asyncio.Queue()
    _queues.setdefault(job_id, []).append(q)
    return q


def unsubscribe(job_id: str, q: "asyncio.Queue[dict]") -> None:
    """Elimina la cola al desconectarse el cliente SSE."""
    bucket = _queues.get(job_id)
    if bucket:
        try:
            bucket.remove(q)
        except ValueError:
            pass
        if not bucket:
            del _queues[job_id]


def publish(job_id: str, event: dict) -> None:
    """Empuja un evento a todos los suscriptores SSE activos del job."""
    for q in list(_queues.get(job_id, [])):
        q.put_nowait(event)
