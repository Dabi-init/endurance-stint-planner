"""Run the local API on loopback. Nothing is uploaded."""

from __future__ import annotations


def main(argv: list[str] | None = None) -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Local Pitwall API. Loopback only.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    uvicorn.run("pitwall_api.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
