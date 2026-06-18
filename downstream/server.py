import asyncio
import sys
import threading
import time

from concurrent import futures

import grpc
from aiohttp import web

import downstream_pb2
import downstream_pb2_grpc


def _ts() -> int:
    return int(time.time() * 1000)


def _log(req_id: str, event: str, detail: str | None = None) -> None:
    line = f"ts={_ts()} req={req_id} stage=downstream event={event}"
    if detail:
        line += f" detail={detail}"
    print(line, flush=True)


async def slow_handler(request: web.Request) -> web.StreamResponse:
    delay = int(request.rel_url.query.get("delay", "10"))
    req_id = request.headers.get("X-Req-ID", f"ds-{_ts()}")

    _log(req_id, "request_received", f"delay={delay}s")

    response = web.StreamResponse()
    response.headers["Content-Type"] = "text/plain"
    await response.prepare(request)

    start = time.monotonic()
    while time.monotonic() - start < delay:
        await asyncio.sleep(0.1)
        try:
            await response.write(b".")
        except (ConnectionResetError, asyncio.CancelledError, Exception):
            _log(req_id, "connection_closed")
            return response

    _log(req_id, "response_sent")
    try:
        await response.write_eof()
    except Exception:
        pass
    return response


async def health_handler(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


class DownstreamServicer(downstream_pb2_grpc.DownstreamServiceServicer):
    def SlowCall(self, request, context):
        req_id = request.req_id or f"grpc-{_ts()}"
        delay = request.delay_seconds or 10

        _log(req_id, "grpc_call_received", f"delay={delay}s")

        start = time.monotonic()
        while time.monotonic() - start < delay:
            time.sleep(0.1)
            if not context.is_active():
                _log(req_id, "grpc_call_cancelled")
                context.set_code(grpc.StatusCode.CANCELLED)
                context.set_details("client cancelled")
                return downstream_pb2.SlowResponse()

        _log(req_id, "grpc_call_completed")
        return downstream_pb2.SlowResponse(message="done")


def serve_grpc(port: int = 50051) -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=20))
    downstream_pb2_grpc.add_DownstreamServiceServicer_to_server(
        DownstreamServicer(), server
    )
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    _log("server", "grpc_started", f"port={port}")
    server.wait_for_termination()


def main() -> None:
    grpc_thread = threading.Thread(target=serve_grpc, daemon=True)
    grpc_thread.start()

    http_port = 8090
    app = web.Application()
    app.router.add_get("/slow", slow_handler)
    app.router.add_get("/health", health_handler)

    _log("server", "started", f"http_port={http_port}")
    sys.stdout.flush()

    web.run_app(app, host="0.0.0.0", port=http_port, access_log=None)


if __name__ == "__main__":
    main()
