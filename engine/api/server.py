import uvicorn
import argparse
import asyncio
import os
import sys
from api.main import app

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    parser = argparse.ArgumentParser(description="Run the FastAPI server")
    parser.add_argument(
        "--port", type=int, required=True, help="Port number to run the server on"
    )
    parser.add_argument(
        "--reload", type=str, default="false", help="Reload the server on code changes"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        help="Uvicorn log level",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of worker processes (default: 1, ignored when --reload is true)",
    )
    args = parser.parse_args()
    reload = args.reload == "true"
    host = os.getenv("API_HOST", "127.0.0.1")

    workers = args.workers
    if workers is None:
        workers = int(os.getenv("API_WORKERS", "1"))

    run_kwargs: dict = {
        "host": host,
        "port": args.port,
        "log_level": args.log_level,
        "reload": reload,
    }
    if not reload and workers > 1:
        run_kwargs["workers"] = workers

    uvicorn.run("api.main:app", **run_kwargs)
