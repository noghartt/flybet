"""Loopback-only control surface; no wallet or external action capability."""

import asyncio
import hashlib
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .anatomy import load_anatomy
from .experiment import Busy, Experiment
from .game import Config
from .insights import InsightArchive
from .protocol import ProtocolConfig
from .templates import CATALOG, VERSION


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str = "random"
    seed: StrictInt = 42
    bankroll_cents: StrictInt = 10000
    stake_cents: StrictInt = 100
    max_decisions: StrictInt = 200
    learning: StrictBool = True
    policy: str = "neural"
    wager_mode: str = "fixed"
    physiology: str = "default"
    vision: str = "default"
    motor: str = "default"
    chemistry: str = "baseline"
    pulse: str = "sustained"
    reward: str = "binary"
    memory: str = "default"
    wealth: str = "off"
    single: StrictBool = False


class Conditioning(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiment: Start
    seeds: StrictInt = 5
    trials: StrictInt = 20
    retention_seconds: StrictInt = 0


class MemoryControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: str


class DashboardFiles(StaticFiles):
    def is_not_modified(self, response_headers, request_headers):
        # Nix fixes mtimes to epoch+1; size/mtime validators cannot identify a build.
        # This small local UI must not combine assets from different package versions.
        return False


def create_app(experiment=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.experiment = experiment or Experiment()
        app.state.insight_archive = InsightArchive(app.state.experiment.runs)
        yield
        app.state.experiment.close()

    app = FastAPI(title="Flybet", lifespan=lifespan)
    web = Path(__file__).with_name("web")
    asset_version = hashlib.sha256(
        b"".join(
            p.name.encode() + b"\0" + p.read_bytes() for p in sorted(web.iterdir()) if p.is_file()
        )
    ).hexdigest()[:16]
    asset_prefix = f"/assets/{asset_version}"
    html = (
        (web / "index.html")
        .read_text()
        .replace('src="/app.js"', f'src="{asset_prefix}/app.js"')
        .replace('href="/style.css"', f'href="{asset_prefix}/style.css"')
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def local_mutations(request, call_next):
        if request.method == "POST":
            # Browsers may read this local app; cross-origin sites may not control it.
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.headers.get('host')}"
            if (origin and origin != expected) or request.headers.get(
                "sec-fetch-site"
            ) == "cross-site":
                return Response("Cross-origin control is disabled", status_code=403)
            if request.headers.get("x-flybet-client") != "local":
                return Response("Missing local control header", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.get("/api/state")
    def state(request: Request):
        return request.app.state.experiment.snapshot()

    @app.get("/api/templates")
    def templates():
        return dict(version=VERSION, calibrated=False, templates=CATALOG)

    @app.post("/api/memory", status_code=202)
    def memory(body: MemoryControl, request: Request):
        try:
            request.app.state.experiment.memory_control(body.operation)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        return {"accepted": True}

    @app.post("/api/protocol", status_code=202)
    def protocol(body: Conditioning, request: Request):
        try:
            config = Config(**body.experiment.model_dump(exclude={"single"}))
            if config.policy != "neural":
                raise ValueError("Conditioning probes require the neural controller")
            settings = ProtocolConfig(body.seeds, body.trials, body.retention_seconds)
            request.app.state.experiment.start_protocol(config, settings)
        except Busy as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"accepted": True}

    @app.get("/api/protocols")
    def protocols(request: Request):
        root = request.app.state.experiment.runs
        paths = sorted(root.glob("*/protocol.json"), reverse=True)
        entries = []
        for path in paths[:200]:
            if path.parent.is_symlink() or path.is_symlink():
                continue
            try:
                report = json.loads(path.read_text())
                entries.append(
                    dict(
                        run_id=path.parent.name,
                        status=report["status"],
                        analysis=report.get("analysis"),
                    )
                )
            except (ValueError, KeyError, OSError):
                continue
        return entries

    @app.get("/api/protocols/{run_id}")
    def protocol_report(run_id: str, request: Request):
        try:
            directory = request.app.state.insight_archive.directory(run_id)
            path = directory / "protocol.json"
            if path.is_symlink() or not path.exists():
                raise FileNotFoundError("Protocol report unavailable")
            return FileResponse(
                path, media_type="application/json", filename=f"{run_id}-protocol.json"
            )
        except (ValueError, FileNotFoundError) as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/runs")
    def recorded_runs(request: Request):
        # The current run has its own live selector; its provenance may still be initializing.
        current = request.app.state.experiment.snapshot()["run_id"]
        return request.app.state.insight_archive.catalog(exclude_run_id=current)

    @app.get("/api/runs/{run_id}/insights")
    def recorded_insights(run_id: str, request: Request, download: bool = False):
        snapshot = request.app.state.experiment.snapshot()
        if run_id == snapshot["run_id"]:
            result = {
                "run_id": run_id,
                "config": snapshot["config"],
                "status": snapshot["status"],
                "decisions": snapshot["decision"],
                "model_identity": snapshot.get("model_identity"),
                "source_identity": snapshot.get("source_identity"),
                "runtime": snapshot.get("runtime"),
                "interventions": snapshot.get("interventions", []),
                "metrics": snapshot["insights"],
                "warnings": ["Only completed decisions are included."] if snapshot["busy"] else [],
            }
        else:
            try:
                result = request.app.state.insight_archive.read(run_id)
            except FileNotFoundError as e:
                raise HTTPException(404, str(e)) from e
            except (ValueError, KeyError, OSError) as e:
                raise HTTPException(422, f"Cannot analyze this record: {e}") from e
        return JSONResponse(
            result,
            headers={
                "Cache-Control": "no-store",
                **(
                    {"Content-Disposition": f'attachment; filename="{run_id}-insights.json"'}
                    if download
                    else {}
                ),
            },
        )

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        return html

    def anatomy(request):
        try:
            return load_anatomy(str(request.app.state.experiment.data.resolve()))
        except (OSError, ValueError, KeyError) as e:
            raise HTTPException(503, f"Anatomical data unavailable: {e}") from e

    @app.get("/api/anatomy")
    def anatomical_metadata(request: Request):
        return anatomy(request).metadata

    @app.get("/api/anatomy/points")
    def anatomical_points(request: Request):
        data = anatomy(request)
        return Response(
            data.binary,
            media_type="application/octet-stream",
            headers={"ETag": f'"{data.metadata["points_sha256"]}"'},
        )

    @app.get("/api/anatomy/neuron/{index}")
    def anatomical_neuron(index: int, request: Request):
        try:
            return anatomy(request).neuron(index)
        except IndexError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/activity")
    def activity(request: Request):
        experiment = request.app.state.experiment
        with experiment.lock:
            packet, identity = experiment.activity_packet, experiment.activity_identity
        if packet is None:
            return Response(status_code=204, headers={"Cache-Control": "no-store"})
        return Response(
            packet,
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Flybet-Run": identity[0],
                "X-Flybet-Ids": identity[1],
            },
        )

    @app.post("/api/run", status_code=202)
    def run(body: Start, request: Request):
        try:
            request.app.state.experiment.start(
                Config(**body.model_dump(exclude={"single"})), body.single
            )
        except Busy as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"accepted": True}

    @app.post("/api/{command}", status_code=202)
    def control(command: str, request: Request):
        experiment = request.app.state.experiment
        try:
            if command == "pause":
                experiment.pause()
            elif command in ("resume", "step"):
                experiment.resume(command == "step")
            else:
                raise HTTPException(404, "Unknown command")
        except (Busy, ValueError) as e:
            raise HTTPException(409, str(e)) from e
        return {"accepted": True}

    @app.get("/api/events")
    async def events(request: Request):
        async def stream():
            while not await request.is_disconnected():
                yield (
                    "data: "
                    + json.dumps(request.app.state.experiment.snapshot(), allow_nan=False)
                    + "\n\n"
                )
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @app.get("/api/retina.png")
    def retina(request: Request):
        experiment = request.app.state.experiment
        with experiment.lock:
            image = experiment.image.copy()
        buffer = io.BytesIO()
        Image.fromarray(image).save(buffer, format="PNG")
        return Response(
            buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"}
        )

    @app.get("/api/export")
    def export(request: Request):
        experiment = request.app.state.experiment
        if not experiment.run_dir or not (experiment.run_dir / "events.jsonl").exists():
            raise HTTPException(404, "No recorded experiment")
        return FileResponse(
            experiment.run_dir / "events.jsonl",
            media_type="application/x-ndjson",
            filename=experiment.run_dir.name + ".jsonl",
        )

    app.mount(asset_prefix, DashboardFiles(directory=web), name="versioned-assets")
    app.mount("/", DashboardFiles(directory=web, html=True), name="dashboard")
    return app
