"""mcp-lightrag: MCP server over streamable HTTP (http://<host>:<port>/mcp) + GET /health.

Tools
  lightrag_query(query, mode=DEFAULT_MODE)  ask the LightRAG knowledge base; returns its answer and
                                            the documents it drew on
  lightrag_insert(text, description="")     add a text to the knowledge base (ENABLE_INSERT=false
                                            removes this tool, leaving the server read-only)
  lightrag_list_documents(page, page_size, status)
                                            list the documents in the knowledge base, newest first
  lightrag_delete(documents)                delete documents by id or name - only with ENABLE_DELETE=true,
                                            because it cannot be undone

The LightRAG key stays in this process: agents call this server, never LightRAG itself.
"""
import contextlib
import hmac
import sys
from typing import Annotated

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from app import lightrag
from app.config import Settings, key_state

S = Settings.from_env()
if key_state(S.lightrag_api_key) == "placeholder":   # visible in `docker logs` right after start-up
    print("WARNING: LIGHTRAG_API_KEY is still the example value from .env.example - LightRAG will refuse every call",
          file=sys.stderr, flush=True)

MODE_HELP = {
    "mix": "ค้นทั้งกราฟความสัมพันธ์และข้อความที่ใกล้เคียง (ครอบคลุมที่สุด)",
    "hybrid": "รวม local และ global",
    "local": "เน้นรายละเอียดของสิ่งที่ถามถึงโดยตรง",
    "global": "เน้นภาพรวมและความเชื่อมโยงในวงกว้าง",
    "naive": "ค้นจากข้อความที่ใกล้เคียงเท่านั้น ไม่ใช้กราฟ",
    "bypass": "ส่งคำถามให้ LLM ตอบโดยไม่ค้นคลัง",
}

QUERY_DESCRIPTION = " ".join(filter(None, [
    "ค้นหาและสรุปคำตอบจากคลังความรู้ LightRAG ซึ่งเก็บเอกสารไว้พร้อมกราฟความสัมพันธ์ระหว่างบุคคล องค์กร สถานที่ และเหตุการณ์",
    f"เนื้อหาในคลัง: {S.kb_description}" if S.kb_description else "",
    "ใช้เมื่อต้องการข้อมูลหรือบริบทจากเอกสารที่จัดเก็บไว้ คำตอบจะระบุเอกสารที่ใช้อ้างอิงไว้ท้ายข้อความ",
    "หากต้องการเพิ่มเอกสารใหม่เข้าคลัง ให้ใช้ lightrag_insert" if S.enable_insert else "",
]))
LIST_DESCRIPTION = (
    "แสดงรายการเอกสารในคลังความรู้ LightRAG เรียงจากใหม่ไปเก่า พร้อมรหัส (id) ชื่อ สถานะ วันที่เพิ่ม และเนื้อหาโดยย่อ "
    "ใช้เมื่อผู้ใช้ถามว่าในคลังมีเอกสารอะไรบ้าง ต้องการตรวจว่าเอกสารที่เพิ่งเพิ่มประมวลผลเสร็จแล้วหรือยัง "
    "หรือต้องการหารหัสของเอกสารก่อนลบ"
)
DELETE_DESCRIPTION = (
    "Delete documents from the LightRAG knowledge base. ลบเอกสารออกจากคลังความรู้ LightRAG "
    "พร้อมข้อมูลทั้งหมดที่สกัดจากเอกสารนั้น ได้แก่ ข้อความ เวกเตอร์ เอนทิตี และความสัมพันธ์ "
    "⚠ ลบแล้วกู้คืนไม่ได้ ต้องยืนยันชื่อเอกสารกับผู้ใช้ก่อนทุกครั้ง "
    "และใช้ lightrag_list_documents ตรวจชื่อหรือรหัสให้ถูกต้องก่อนลบ"
)
MODE_DESCRIPTION = ("วิธีค้นหา: " + " · ".join(f"{m} = {MODE_HELP[m]}" for m in S.query_modes)
                    + f" (หากไม่ระบุจะใช้ {S.default_mode})")
INSERT_DESCRIPTION = (
    "Insert / add / store a document, report, or summary into the LightRAG knowledge base. "
    "เพิ่มเอกสาร รายงาน หรือสรุปเข้าคลังความรู้ LightRAG "
    "ระบบจะสกัดเอนทิตีและความสัมพันธ์ในเบื้องหลัง จึงอาจใช้เวลาสักครู่ก่อนที่จะค้นหาเนื้อหาใหม่ได้"
)

mcp = MCPServer(
    name="lightrag",
    version="0.3.0",
    instructions=("ค้นหาข้อมูลและดูรายการเอกสารในคลังความรู้ LightRAG"
                  + (" เพิ่มเอกสารเข้าคลัง" if S.enable_insert else "")
                  + (" และลบเอกสารออกจากคลัง (ต้องยืนยันกับผู้ใช้ก่อนลบ)" if S.enable_delete else "")
                  + (f" เนื้อหาในคลัง: {S.kb_description}" if S.kb_description else "")),
)


# ------------------------------------------------------------------ tools
async def lightrag_query(
    query: Annotated[str, Field(description="คำถามหรือหัวข้อที่ต้องการค้นหาในคลังความรู้")],
    mode: Annotated[str, Field(description=MODE_DESCRIPTION, json_schema_extra={"enum": S.query_modes})]
    = S.default_mode,
) -> str:
    query = (query or "").strip()
    if not query:
        return "[query is empty - say what to look for]"
    mode = (mode or "").strip().lower()
    if mode not in S.query_modes:            # agents sometimes invent a mode; never fail on it
        mode = S.default_mode
    return await lightrag.query(S, query, mode)


async def lightrag_insert(
    text: Annotated[str, Field(description="เนื้อหาที่ต้องการเพิ่มเข้าคลัง (Markdown หรือข้อความธรรมดา)")],
    description: Annotated[str, Field(description=(
        "ชื่อเอกสารสั้น ๆ ซึ่งจะแสดงเป็นแหล่งอ้างอิงในคำตอบ เช่น 'quarterly-report-2026-q3' "
        "หากไม่ระบุ ระบบจะตั้งชื่อตามวันและเวลา"))] = "",
) -> str:
    text = (text or "").strip()
    if not text:
        return "[text is empty - nothing to insert]"
    return await lightrag.insert(S, text, (description or "").strip())


async def lightrag_list_documents(
    page: Annotated[int, Field(description="หน้าที่ต้องการ เริ่มที่ 1", ge=1)] = 1,
    page_size: Annotated[int, Field(description="จำนวนเอกสารต่อหน้า (10-200)", ge=10, le=200)] = 20,
    status: Annotated[str, Field(description=(
        "แสดงเฉพาะเอกสารที่มีสถานะนี้ หากเว้นว่างจะแสดงทุกสถานะ: processed = พร้อมค้นหา · "
        "pending, parsing, analyzing, processing = กำลังประมวลผล · failed = ประมวลผลไม่สำเร็จ"),
        json_schema_extra={"enum": ["", *lightrag.DOC_STATUSES]})] = "",
) -> str:
    status = (status or "").strip().lower()
    if status and status not in lightrag.DOC_STATUSES:
        return f"[unknown status {status!r} - use one of {', '.join(lightrag.DOC_STATUSES)}, or leave it empty]"
    return await lightrag.list_documents(S, page, page_size, status)


async def lightrag_delete(
    documents: Annotated[list[str], Field(description=(
        "รหัสเอกสาร (ขึ้นต้นด้วย doc-) หรือชื่อเอกสาร ตามที่แสดงใน lightrag_list_documents หรือในแหล่งอ้างอิงของคำตอบ "
        "ระบุได้หลายรายการ"), min_length=1)],
) -> str:
    return await lightrag.delete(S, documents)


mcp.add_tool(lightrag_query, description=QUERY_DESCRIPTION,
             annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
mcp.add_tool(lightrag_list_documents, description=LIST_DESCRIPTION,
             annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
if S.enable_insert:
    mcp.add_tool(lightrag_insert, description=INSERT_DESCRIPTION,
                 annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False))
if S.enable_delete:
    mcp.add_tool(lightrag_delete, description=DELETE_DESCRIPTION,
                 annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False))


# ------------------------------------------------------------------ http app
async def health_report() -> dict:
    """ok = LightRAG answers and accepts the key. problems explains every reason it does not."""
    state = key_state(S.lightrag_api_key)
    rag = await lightrag.check(S)
    problems = []
    if state == "placeholder":
        problems.append("LIGHTRAG_API_KEY is still the example value from .env.example - "
                        "put the LightRAG server's key in .env")
    if not rag["reachable"]:
        problems.append(f"LightRAG does not answer at LIGHTRAG_URL {S.lightrag_url} - "
                        "is it running, and on the same docker network?")
    elif rag["key_accepted"] is False:
        problems.append("LightRAG refused LIGHTRAG_API_KEY" + (" (it is empty)" if state == "empty" else "")
                        + " - it must match LIGHTRAG_API_KEY of the LightRAG server")
    return {"ok": not problems, "lightrag_url": S.lightrag_url, "key_configured": state == "set",
            "lightrag": rag, "modes": S.query_modes, "default_mode": S.default_mode,
            "insert_enabled": S.enable_insert, "delete_enabled": S.enable_delete, "auth": bool(S.auth_token), "problems": problems}


async def health(_: Request) -> JSONResponse:
    return JSONResponse(await health_report())


class BearerAuth:
    def __init__(self, app, token: str):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.token and scope["path"].startswith("/mcp"):
            got = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
            if not hmac.compare_digest(got, f"Bearer {self.token}"):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp", stateless_http=True, host=S.host,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@contextlib.asynccontextmanager
async def lifespan(app):
    async with mcp_app.router.lifespan_context(app):
        yield


app = BearerAuth(Starlette(routes=[Route("/health", health), Mount("/", app=mcp_app)], lifespan=lifespan), S.auth_token)

if __name__ == "__main__":
    uvicorn.run(app, host=S.host, port=S.port, log_level="info")
