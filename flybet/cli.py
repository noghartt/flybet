import argparse
import json
import time


def main():
    parser = argparse.ArgumentParser(description="Flybet — MaleCNS v1.0, simulated money only")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "prepare", help="Download, verify and compile the official full retained dataset"
    )
    sub.add_parser("verify", help="Verify compiled dataset checksums")
    server = sub.add_parser("serve", help="Open a local experiment dashboard")
    server.add_argument("--port", type=int, default=8765)
    run = sub.add_parser("run", help="Run an experiment without the browser")
    run.add_argument("--scenario", choices=["random", "fly", "house"], default="random")
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--decisions", type=int, default=20)
    run.add_argument("--frozen", action="store_true")
    run.add_argument("--policy", choices=["neural", "random-baseline"], default="neural")
    conditioning = sub.add_parser("condition", help="Run paired full-connectome learning controls")
    conditioning.add_argument("--seeds", type=int, default=5)
    conditioning.add_argument("--trials", type=int, default=20)
    conditioning.add_argument("--retention-seconds", type=int, default=0)
    conditioning.add_argument("--seed", type=int, default=42)
    from .templates import CATALOG

    for command in (run, conditioning):
        command.add_argument("--wager-mode", choices=["fixed", "adaptive"], default="fixed")
        command.add_argument("--stake-cents", type=int, default=100)
        command.add_argument("--bankroll-cents", type=int, default=10000)
        for name, choices in CATALOG.items():
            command.add_argument(f"--{name}", choices=list(choices), default=next(iter(choices)))
    args = parser.parse_args()
    if args.command in ("prepare", "verify"):
        from .data import prepare, verify

        result = prepare() if args.command == "prepare" else verify()
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in ["dataset", "neurons", "edges", "contacts", "plastic_edges"]
                },
                indent=2,
            )
        )
    elif args.command == "serve":
        import uvicorn

        from .server import create_app

        print(f"Flybet dashboard: http://127.0.0.1:{args.port}", flush=True)
        uvicorn.run(create_app(), host="127.0.0.1", port=args.port, access_log=False)
    elif args.command in ("run", "condition"):
        from .experiment import Experiment
        from .game import Config

        experiment = Experiment()
        try:
            config = Config(
                scenario=getattr(args, "scenario", "random"),
                seed=args.seed,
                max_decisions=getattr(args, "decisions", 20),
                learning=not getattr(args, "frozen", False),
                policy=getattr(args, "policy", "neural"),
                wager_mode=args.wager_mode,
                stake_cents=args.stake_cents,
                bankroll_cents=args.bankroll_cents,
                **{name: getattr(args, name) for name in CATALOG},
            )
            if args.command == "condition":
                from .protocol import ProtocolConfig

                experiment.start_protocol(
                    config, ProtocolConfig(args.seeds, args.trials, args.retention_seconds)
                )
            else:
                experiment.start(config)
            last = -1
            while experiment.thread.is_alive():
                state = experiment.snapshot()
                if state["decision"] != last:
                    print(
                        json.dumps({k: state[k] for k in ["run_id", "status", "decision", "game"]}),
                        flush=True,
                    )
                    last = state["decision"]
                time.sleep(0.2)
            state = experiment.snapshot()
            print(
                json.dumps(
                    {
                        k: state.get(k)
                        for k in ["run_id", "status", "game", "telemetry", "protocol", "error"]
                    }
                ),
                flush=True,
            )
            if state["status"] == "error":
                raise SystemExit(1)
        except KeyboardInterrupt:
            experiment.pause()
        finally:
            experiment.close()
