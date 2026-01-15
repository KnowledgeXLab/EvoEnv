import json
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager
import argparse
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from environment import Environment


parser = argparse.ArgumentParser(description="InternBench Human Interface Server")
parser.add_argument(
    "--task-root",
    type=str,
    default=str('tasks/test_new'),
    help="Task root directory (default: %(default)s)",
)
parser.add_argument(
    "--log-path",
    type=str,
    default="outputs/test_new",
    help="Log file path (default: %(default)s)",
)

args = parser.parse_args()

# Override globals before starting uvicorn so that Environment and
# derived paths use the CLI-provided values when running as a script.
task_root_path = Path(args.task_root).resolve()
log_path = args.log_path


env = Environment(
    task_path=str(task_root_path),
    log_level="INFO",
    log_path=log_path,
)

# Cloud disk and workspace roots (under the same task root)
CLOUD_DISK_ROOT = (task_root_path / "cloud_disk").resolve()
WORKSPACE_ROOT = (task_root_path / "workspace").resolve()


def _safe_subpath(root: Path, rel: str) -> Path:
    """Return a safe sub-path under *root* for the given relative path.

    Prevent path traversal by resolving and ensuring the result stays
    within the root directory.
    """
    rel = rel.lstrip('/') if rel else ''
    candidate = (root / rel).resolve()
    root_resolved = root.resolve()
    if root_resolved not in candidate.parents and candidate != root_resolved:
        raise ValueError("Invalid path: outside of root directory")
    return candidate

default_agent_name: Optional[str] = env.ego_agent_names[0] if env.ego_agent_names else None
task_description = env.generate_tasks_prompt(default_agent_name) if default_agent_name else "No agent found."


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context.

    This replaces the deprecated ``@app.on_event("shutdown")`` hook.
    Any setup logic can go before the ``yield``; teardown/cleanup goes
    in the ``finally`` block so it's always executed on shutdown.
    """
    try:
        # Startup logic (if needed) goes here.
        yield
    finally:
        try:
            env.close()
        except Exception as e:  # pragma: no cover - safety net
            print(f"[shutdown] env.close() failed: {e}")


app = FastAPI(lifespan=lifespan)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"

TEMPLATE_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(TEMPLATE_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "task_description": task_description,
            "agent_name": default_agent_name,
        },
    )


class DirectMessagePayload(BaseModel):
    sender: str
    receiver: str
    message: str


class GroupMessagePayload(BaseModel):
    sender: str
    group_id: str
    message: str


class CreateGroupPayload(BaseModel):
    creator: str
    members: str


class CalendarGetRoomsPayload(BaseModel):
    start: str
    end: str


class CalendarBookPayload(BaseModel):
    applicant: str
    attendees: str
    room_name: str
    start: str
    end: str


class CalendarAttendPayload(BaseModel):
    agent_name: str
    room_name: str
    start: str
    end: str


class CalendarCancelPayload(BaseModel):
    applicant: str
    room_name: str
    start: str
    end: str


class ListPathPayload(BaseModel):
    """Generic payload for listing a sub-directory.

    ``path`` is interpreted as a POSIX-style relative path under the
    corresponding root (``cloud_disk/`` or ``workspace/``).
    """

    path: str = ""  # empty string means the root


class CopyFilePayload(BaseModel):
    """Payload for copying a file from cloud_disk to workspace."""

    src_path: str  # relative to cloud_disk root
    dst_path: str  # relative to workspace root


class FileViewSavePayload(BaseModel):
    """Payload for saving an edited text file under workspace root."""

    path: str
    content: str


class CommandExecutePayload(BaseModel):
    """Payload for executing a shell command in sandbox via ExecuteCommand tool."""

    command: str

class WebsiteHistoricalPayload(BaseModel):
    """Payload for querying historical page load times."""

    time_window: str = "last_7_days"
    page_url: Optional[str] = None


class WebsitePerformancePayload(BaseModel):
    """Payload for querying website performance summary."""

    time_window: str = "last_24_hours"


class WebsiteErrorLogsPayload(BaseModel):
    """Payload for querying error logs of a server."""

    server_id: str
    lines: int = 20


@app.post("/api/evaluate")
async def api_evaluate():
    """Run task evaluation via Environment.evaluate()."""
    try:
        result = env.evaluate()
        return JSONResponse(content={"detail": json.dumps(result, ensure_ascii=False, indent=4)})
    except Exception as exc:  # pragma: no cover - safety net
        return JSONResponse(status_code=500, content={"detail": f"Evaluation failed: {exc}"})


@app.post("/api/command/execute")
async def api_command_execute(payload: CommandExecutePayload):
    """Execute a shell command via ExecuteCommand tool in Docker sandbox."""
    cmd = payload.command.strip()
    if not cmd:
        return JSONResponse(status_code=400, content={"detail": "Command must not be empty."})

    return _call_tool("ExecuteCommand", command=cmd)


def _call_tool(tool_name: str, **kwargs) -> JSONResponse:
    """Call a toolbox tool via Environment.tool_manager and wrap result.

    This helper keeps API handlers thin and delegates the actual execution
    to the Environment, which manages tool loading.
    """
    tool = env.tool_manager.get_tool(tool_name)
    if tool is None:
        return JSONResponse(status_code=404, content={"detail": f"Tool '{tool_name}' not found."})
    try:
        result = tool(**kwargs)
    except TypeError as exc:
        # Parameter mismatch or validation error coming from the tool layer.
        return JSONResponse(status_code=400, content={"detail": f"Invalid parameters for tool '{tool_name}': {exc}"})
    except Exception as exc:  # pragma: no cover - safety net
        return JSONResponse(status_code=500, content={"detail": f"Internal error when calling tool '{tool_name}': {exc}"})

    # Tools in this project often return plain strings; we normalize to JSON.
    if isinstance(result, str):
        return JSONResponse(content={"detail": result})
    return JSONResponse(content=result)

@app.post("/api/website/historical-load-times")
async def api_website_historical(payload: WebsiteHistoricalPayload):
    """Get historical average page load times via GetHistoricalLoadTimes tool."""
    return _call_tool(
        "GetHistoricalLoadTimes",
        time_window=payload.time_window,
        page_url=payload.page_url,
    )

@app.post("/api/website/system-health")
async def api_website_system_health():
    """Get real-time system health via GetRealTimeSystemHealth tool."""
    return _call_tool("GetRealTimeSystemHealth")

@app.post("/api/website/list-services")
async def api_website_list_services():
    """List monitored services via ListMonitoredServices tool."""
    return _call_tool("ListMonitoredServices")

@app.post("/api/website/performance-summary")
async def api_website_performance_summary(payload: WebsitePerformancePayload):
    """Get performance summary via GetPerformanceSummary tool."""
    return _call_tool("GetPerformanceSummary", time_window=payload.time_window)

@app.post("/api/website/error-logs")
async def api_website_error_logs(payload: WebsiteErrorLogsPayload):
    """Get error logs via GetErrorLogs tool."""
    return _call_tool("GetErrorLogs", server_id=payload.server_id, lines=payload.lines)


@app.post("/api/chat/list-users")
async def api_list_users():
    """List all registered users via ListUsers tool."""
    return _call_tool("ListUsers")


@app.post("/api/chat/list-groups")
async def api_list_groups():
    """List all chat groups via ListChatGroups tool."""
    return _call_tool("ListChatGroups")


@app.post("/api/chat/send-message")
async def api_send_message(payload: DirectMessagePayload):
    """Send a direct message via SendMessage tool."""
    return _call_tool(
        "SendMessage",
        sender=payload.sender,
        receiver=payload.receiver,
        message=payload.message,
    )


@app.post("/api/chat/send-group-message")
async def api_send_group_message(payload: GroupMessagePayload):
    """Send a group message via SendGroupMessage tool."""
    # Group ID is declared as int in the tool, but comes as string from UI.
    try:
        group_id_int = int(payload.group_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "group_id must be an integer."})

    return _call_tool(
        "SendGroupMessage",
        sender=payload.sender,
        group_id=group_id_int,
        message=payload.message,
    )


@app.post("/api/chat/create-group")
async def api_create_group(payload: CreateGroupPayload):
    """Create a new chat group via CreateChatGroup tool.

    The frontend sends comma-separated member names in ``members``.
    The ``creator`` must be included in the final member list.
    """
    # Split by comma, strip whitespace, and drop empty entries.
    raw_members = [m.strip() for m in payload.members.split(',')]
    group_members = [m for m in raw_members if m]

    if not payload.creator.strip():
        return JSONResponse(status_code=400, content={"detail": "creator must not be empty."})

    # Ensure creator is part of the group.
    if payload.creator not in group_members:
        group_members.insert(0, payload.creator)

    if len(set(group_members)) < 2:
        return JSONResponse(status_code=400, content={"detail": "A group must contain at least two unique members."})

    return _call_tool("CreateChatGroup", agent_name=payload.creator, group_members=group_members)


@app.post("/api/calendar/get-available-rooms")
async def api_get_available_rooms(payload: CalendarGetRoomsPayload):
    """Get available meeting rooms via GetAvailableRooms tool."""
    return _call_tool(
        "GetAvailableRooms",
        start=payload.start,
        end=payload.end,
    )


@app.post("/api/calendar/book-meeting")
async def api_book_meeting(payload: CalendarBookPayload):
    """Book a meeting via BookMeeting tool."""
    return _call_tool(
        "BookMeeting",
        applicant=payload.applicant,
        attendees=payload.attendees,
        room_name=payload.room_name,
        start=payload.start,
        end=payload.end,
    )


@app.post("/api/calendar/attend-meeting")
async def api_attend_meeting(payload: CalendarAttendPayload):
    """Attend a meeting via AttendMeeting tool."""
    return _call_tool(
        "AttendMeeting",
        agent_name=payload.agent_name,
        room_name=payload.room_name,
        start=payload.start,
        end=payload.end,
    )


@app.post("/api/calendar/cancel-meeting")
async def api_cancel_meeting(payload: CalendarCancelPayload):
    """Cancel a meeting via CancelMeeting tool."""
    return _call_tool(
        "CancelMeeting",
        applicant=payload.applicant,
        room_name=payload.room_name,
        start=payload.start,
        end=payload.end,
    )


@app.post("/api/cloud/list-cloud")
async def api_list_cloud(payload: ListPathPayload):
    """List contents under the cloud_disk root.

    Returns JSON with ``path`` (normalized relative path), ``breadcrumbs``,
    and ``entries`` (files and directories, with a simple type flag).
    """
    try:
        target_dir = _safe_subpath(CLOUD_DISK_ROOT, payload.path)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    if not target_dir.exists() or not target_dir.is_dir():
        return JSONResponse(status_code=404, content={"detail": "Directory not found"})

    rel_path = str(target_dir.relative_to(CLOUD_DISK_ROOT)) if target_dir != CLOUD_DISK_ROOT else ""
    breadcrumbs = []
    if rel_path:
        parts = rel_path.split('/')
        acc = []
        for part in parts:
            acc.append(part)
            breadcrumbs.append({"name": part, "path": '/'.join(acc)})

    entries = []
    for child in sorted(target_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        entries.append(
            {
                "name": child.name,
                "is_dir": child.is_dir(),
                "path": str(child.relative_to(CLOUD_DISK_ROOT)),
            }
        )

    return JSONResponse(
        content={
            "path": rel_path,
            "breadcrumbs": breadcrumbs,
            "entries": entries,
        }
    )


@app.post("/api/cloud/list-workspace")
async def api_list_workspace(payload: ListPathPayload):
    """List contents under the workspace root."""

    try:
        target_dir = _safe_subpath(WORKSPACE_ROOT, payload.path)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    if not target_dir.exists() or not target_dir.is_dir():
        return JSONResponse(status_code=404, content={"detail": "Directory not found"})

    rel_path = str(target_dir.relative_to(WORKSPACE_ROOT)) if target_dir != WORKSPACE_ROOT else ""
    breadcrumbs = []
    if rel_path:
        parts = rel_path.split('/')
        acc = []
        for part in parts:
            acc.append(part)
            breadcrumbs.append({"name": part, "path": '/'.join(acc)})

    entries = []
    for child in sorted(target_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        entries.append(
            {
                "name": child.name,
                "is_dir": child.is_dir(),
                "path": str(child.relative_to(WORKSPACE_ROOT)),
            }
        )

    return JSONResponse(
        content={
            "path": rel_path,
            "breadcrumbs": breadcrumbs,
            "entries": entries,
        }
    )


@app.post("/api/cloud/copy-to-workspace")
async def api_copy_to_workspace(payload: CopyFilePayload):
    """Copy a single file from cloud_disk to workspace.

    ``src_path`` is interpreted under ``cloud_disk/`` and must refer to an
    existing regular file. ``dst_path`` is interpreted under ``workspace/``.
    Parent directories are created automatically if needed.
    """
    try:
        src_abs = _safe_subpath(CLOUD_DISK_ROOT, payload.src_path)
        dst_abs = _safe_subpath(WORKSPACE_ROOT, payload.dst_path)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    if not src_abs.exists() or not src_abs.is_file():
        return JSONResponse(status_code=404, content={"detail": "Source file not found"})

    dst_abs.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Use shutil to preserve file contents.
        import shutil

        shutil.copy2(src_abs, dst_abs)
    except Exception as exc:  # pragma: no cover - safety net
        return JSONResponse(status_code=500, content={"detail": f"Copy failed: {exc}"})

    return JSONResponse(
        content={
            "detail": "File copied successfully",
            "src_path": str(src_abs.relative_to(CLOUD_DISK_ROOT)),
            "dst_path": str(dst_abs.relative_to(WORKSPACE_ROOT)),
        }
    )


@app.get("/api/file-view/raw")
async def api_file_view_raw(path: str):
    """Return raw file content under workspace for binary preview (images, video, pdf).

    ``path`` is a relative path under ``workspace/``.
    """
    try:
        abs_path = _safe_subpath(WORKSPACE_ROOT, path)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    if not abs_path.exists() or not abs_path.is_file():
        return JSONResponse(status_code=404, content={"detail": "File not found"})

    suffix = abs_path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}:
        media_type = f"image/{suffix.lstrip('.')}" if suffix != ".jpg" else "image/jpeg"
    elif suffix in {".mp4", ".webm", ".ogg", ".mov", ".m4v"}:
        media_type = "video/mp4" if suffix == ".mp4" else "video/mp4"
    elif suffix == ".pdf":
        media_type = "application/pdf"
    else:
        media_type = "application/octet-stream"

    def iterfile():
        with abs_path.open("rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(iterfile(), media_type=media_type)


@app.get("/api/file-view/content")
async def api_file_view_content(path: str):
    """Return text content of a file under workspace.

    Used by File View & Edit tab for text-editable files.
    """
    try:
        abs_path = _safe_subpath(WORKSPACE_ROOT, path)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    if not abs_path.exists() or not abs_path.is_file():
        return JSONResponse(status_code=404, content={"detail": "File not found"})

    try:
        try:
            text = abs_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = abs_path.read_text(encoding="latin-1")
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Failed to read file: {exc}"})

    return JSONResponse(content={"content": text})


@app.post("/api/file-view/save")
async def api_file_view_save(payload: FileViewSavePayload):
    """Save content to a text file under workspace.

    The path is always interpreted under ``workspace/`` and must remain
    within that directory.
    """
    try:
        abs_path = _safe_subpath(WORKSPACE_ROOT, payload.path)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    if not abs_path.exists() or not abs_path.is_file():
        return JSONResponse(status_code=404, content={"detail": "File not found"})

    try:
        abs_path.write_text(payload.content, encoding="utf-8")
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Failed to save file: {exc}"})

    return JSONResponse(content={"detail": "File saved successfully"})

if __name__ == "__main__":

    print(f"Server is starting. Please open: http://127.0.0.1:8000")
    uvicorn.run("human_interface:app", host="127.0.0.1", port=8000, reload=True)
