import argparse
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

def main():
    parser = argparse.ArgumentParser(description="Start the local RAN Sentinel demo.")
    parser.add_argument("--port", type=int, default=8000, help="local port (default: 8000)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    # Check before importing the app: startup resets the demo database.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", args.port))
        except OSError:
            print(f"Port {args.port} is unavailable. An earlier server may already be running.", file=sys.stderr)
            print(f"Open http://127.0.0.1:{args.port}/ops/ or choose another port: python run.py --port 8001", file=sys.stderr)
            return 1
    try:
        import uvicorn
    except ModuleNotFoundError:
        print("Dependencies are missing. Run: python -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    print(f"Operations: http://127.0.0.1:{args.port}/ops/", flush=True)
    print(f"Customer app: http://127.0.0.1:{args.port}/connect/", flush=True)
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
