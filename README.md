# mcp-lightrag

MCP server ที่ช่วยให้ AI agent ที่รองรับ MCP เช่น Hermes ถามตอบ เพิ่ม ดูรายการ และลบเอกสารในคลังความรู้ [LightRAG](https://github.com/HKUDS/LightRAG) ได้โดยตรง
ทำงานบน Docker ในโหมด **streamable HTTP** โดย agent ไม่ต้องรู้ API key ของ LightRAG

ผู้พัฒนา: **Chacharin Lertyosbordin**

> โปรเจกต์นี้เป็นตัวกลางระหว่าง agent กับ LightRAG server เท่านั้น ไม่ได้รวม LightRAG มาด้วย
> LightRAG พัฒนาโดย HKUDS ภายใต้สัญญาอนุญาต MIT และโปรเจกต์นี้ไม่ใช่ผลงานทางการของทีม LightRAG

## เครื่องมือที่มีให้

| เครื่องมือ | หน้าที่ | API ของ LightRAG ที่ใช้ | ค่าเริ่มต้น |
|---|---|---|---|
| `lightrag_query` | ถามคำถาม แล้วรับคำตอบที่สรุปจากเอกสารในคลัง พร้อมรายชื่อเอกสารอ้างอิง | `POST /query` | เปิดเสมอ |
| `lightrag_list_documents` | ดูรายการเอกสารในคลัง พร้อมรหัส ชื่อ สถานะ และเนื้อหาโดยย่อ | `POST /documents/paginated` | เปิดเสมอ |
| `lightrag_insert` | เพิ่มข้อความ รายงาน หรือสรุปเข้าคลัง | `POST /documents/text` | เปิด (ปิดได้ด้วย `ENABLE_INSERT=false`) |
| `lightrag_delete` | ลบเอกสารพร้อมข้อมูลทั้งหมดที่สกัดจากเอกสารนั้น | `DELETE /documents/delete_document` | **ปิด** (เปิดได้ด้วย `ENABLE_DELETE=true`) |

เครื่องมือที่ปิดไว้จะไม่แสดงให้ agent เห็นเลย agent จึงเรียกใช้ไม่ได้

## หลักการทำงาน

```
agent ──POST /mcp──▶ mcp-lightrag (container)
                       ① ตรวจ token หากกำหนด MCP_AUTH_TOKEN ไว้
                       ② ส่งคำขอไปยัง LightRAG พร้อม LIGHTRAG_API_KEY
                     ◀── ส่งผลลัพธ์กลับไปยัง agent
```

LightRAG ใช้ LLM สรุปคำตอบทุกครั้งที่ถาม และใช้ LLM สกัดเอนทิตีกับความสัมพันธ์ทุกครั้งที่เพิ่มเอกสาร ค่าใช้จ่ายจึงขึ้นอยู่กับ LLM ที่ตั้งไว้ใน LightRAG server
ส่วน mcp-lightrag ไม่เก็บสถานะการทำงาน ไม่มีฐานข้อมูล และไม่ต้อง mount โฟลเดอร์ใด ๆ

## เริ่มต้นใช้งาน

### สิ่งที่ต้องเตรียม

- **Docker** (Docker Desktop หรือ Docker Engine)
- **LightRAG server** ที่ทำงานอยู่แล้ว ([วิธีติดตั้ง](https://github.com/HKUDS/LightRAG#install-lightrag-server)) และอยู่ใน docker network เดียวกับ agent
- **API key ของ LightRAG** คือค่า `LIGHTRAG_API_KEY` ที่ตั้งไว้ใน LightRAG server ซึ่ง**จำเป็นต้องมี** หาก LightRAG ยังไม่ได้ตั้ง key ให้ตั้งที่ LightRAG ก่อน (ดูหัวข้อ[ความปลอดภัย](#ความปลอดภัย))

### ขั้นตอนการติดตั้ง

```bash
git clone https://github.com/chacharin/mcp-lightrag.git
cd mcp-lightrag
cp .env.example .env                  # จากนั้นใส่ LIGHTRAG_URL และ LIGHTRAG_API_KEY ในไฟล์ .env
docker network create agent_network   # สร้างครั้งแรกครั้งเดียว หากต้องการใช้ชื่ออื่นให้กำหนดใน DOCKER_NETWORK
docker network connect agent_network <ชื่อ container ของ LightRAG>   # หาก LightRAG ยังไม่อยู่ใน network นี้
docker compose up -d --build
curl http://127.0.0.1:8806/health
```

หาก `/health` ตอบ `"ok": true` แปลว่าเชื่อมต่อ LightRAG ได้และ LightRAG ยอมรับ key แล้ว
หากยังมีปัญหา ให้ดูรายการ `problems` ซึ่งจะบอกสาเหตุ เช่น ยังใช้ key ตัวอย่างจาก `.env.example` หรือเชื่อมต่อ `LIGHTRAG_URL` ไม่ได้

คำอธิบายการตั้งค่าทั้งหมดอยู่ในไฟล์ [`.env.example`](.env.example) โดยในไฟล์ `.env` ให้กำหนดเฉพาะค่าที่จำเป็น และค่าที่ต้องการเปลี่ยนจากค่าเริ่มต้น
เมื่อแก้ไข `.env` แล้ว ให้สั่ง `docker compose up -d` อีกครั้ง โดยไม่ต้อง build ใหม่

### การเชื่อมต่อกับ MCP client

ตัวอย่างการตั้งค่าใน Hermes (`config.yaml`):

```yaml
mcp_servers:
  lightrag:
    url: http://mcp-lightrag:8700/mcp
    timeout: 180        # ควรนานกว่า QUERY_TIMEOUT_SECONDS (ค่าเริ่มต้น 120 วินาที)
```

หากกำหนด `MCP_AUTH_TOKEN` ไว้ ให้เพิ่ม header `Authorization: Bearer <token>` ในการตั้งค่าของ client ด้วย
สำหรับ client ที่อยู่นอก docker network ให้ใช้ `http://<IP ของเครื่อง>:8806/mcp`

## วิธีใช้งาน

เมื่อเชื่อมต่อแล้ว ผู้ใช้เพียงพิมพ์สั่ง agent ด้วยภาษาปกติ agent จะเลือกเครื่องมือและกรอกค่าให้เอง
หัวข้อนี้อธิบายว่าแต่ละงานควรสั่งอย่างไร และเครื่องมือรับค่าอะไรบ้าง

### 1. ถามตอบจากคลังความรู้

ตัวอย่างคำสั่ง:

> ค้นจากคลังความรู้ว่ามีรายงานเรื่องการใช้ VRAM ของ LLM ว่าอย่างไรบ้าง
> สรุปภาพรวมของเอกสารทั้งหมดในคลังความรู้

agent จะเรียก `lightrag_query`

| ค่า | จำเป็น | ความหมาย |
|---|---|---|
| `query` | ✓ | คำถามหรือหัวข้อที่ต้องการค้นหา |
| `mode` | | วิธีค้นหา หากไม่ระบุจะใช้ `DEFAULT_MODE` (ค่าเริ่มต้น `hybrid`) |

วิธีค้นหาแต่ละแบบเหมาะกับคำถามต่างกัน

| `mode` | เหมาะกับ |
|---|---|
| `local` | คำถามเจาะจงเกี่ยวกับบุคคล องค์กร หรือเหตุการณ์ใดเหตุการณ์หนึ่ง |
| `global` | คำถามภาพรวม เช่น แนวโน้ม หรือความเชื่อมโยงระหว่างหลายเรื่อง |
| `hybrid` | ใช้ได้กับคำถามทั่วไป เพราะรวม `local` และ `global` |
| `mix` | ต้องการคำตอบที่ครอบคลุมที่สุด เพราะค้นทั้งกราฟความสัมพันธ์และข้อความที่ใกล้เคียง |
| `naive` | ค้นจากข้อความที่ใกล้เคียงเท่านั้นโดยไม่ใช้กราฟ เร็วที่สุด |

คำตอบเป็นข้อความที่ LightRAG สรุปจากเอกสารในคลัง และระบุชื่อเอกสารที่ใช้อ้างอิงไว้ท้ายข้อความ เช่น

```
… VRAM ขั้นต่ำประมาณ 5-6 GB สำหรับโมเดลขนาด 7B แบบ INT4 …

### References
- [1] report_VRAM_LLM_local_17-10-2026
```

หาก LightRAG ตอบว่าไม่พบข้อมูลที่เกี่ยวข้อง แปลว่าในคลังไม่มีเนื้อหาที่ตรงกับคำถาม
แต่หากทุกคำถามได้คำตอบนี้ ให้ตรวจ log ของ LightRAG เพราะอาจเกิดจาก embedding model ใช้งานไม่ได้ เช่น โควตาของผู้ให้บริการหมด

### 2. เพิ่มเอกสารเข้าคลัง

ตัวอย่างคำสั่ง:

> เก็บรายงานนี้เข้าคลังความรู้ โดยตั้งชื่อว่า monthly-report-2026-10
> สรุปข่าวเมื่อสักครู่ แล้วเพิ่มสรุปนั้นเข้าคลังความรู้

agent จะเรียก `lightrag_insert`

| ค่า | จำเป็น | ความหมาย |
|---|---|---|
| `text` | ✓ | เนื้อหาที่ต้องการเพิ่ม (Markdown หรือข้อความธรรมดา) |
| `description` | | ชื่อเอกสาร ซึ่งจะแสดงเป็นแหล่งอ้างอิงในคำตอบ และใช้ระบุเอกสารเมื่อต้องการลบ หากไม่ระบุ ระบบจะตั้งชื่อเป็น `insert-<วันที่>-<เวลา>` |

ระบบจะแทนช่องว่างและอักขระที่ใช้ในชื่อไฟล์ไม่ได้ (เช่น `/` `:` `?`) ด้วย `-` และตัดชื่อให้ยาวไม่เกิน 80 ตัวอักษร ส่วนอักษรภาษาไทยคงไว้ตามเดิม
ผลลัพธ์ที่ได้กลับมาจะมีชื่อที่ระบบใช้จริงอยู่ใน `file_source`

LightRAG จะรับเอกสารทันที แล้วจึงสกัดเอนทิตีและความสัมพันธ์ในเบื้องหลัง ซึ่งอาจใช้เวลาตั้งแต่หลายวินาทีถึงหลายนาที ขึ้นกับความยาวของเอกสาร
ระหว่างนั้นเอกสารยังค้นหาไม่ได้ ตรวจได้ว่าประมวลผลเสร็จแล้วหรือยังด้วย `lightrag_list_documents` (สถานะ `processed` = พร้อมค้นหา)

เครื่องมือนี้รับเฉพาะข้อความ หากต้องการเพิ่มไฟล์ PDF, Word หรือไฟล์อื่น ให้อัปโหลดผ่าน WebUI ของ LightRAG

### 3. ดูรายการเอกสารในคลัง

ตัวอย่างคำสั่ง:

> ตอนนี้ในคลังความรู้มีเอกสารอะไรบ้าง
> รายงานที่เพิ่งเพิ่มเข้าไป ประมวลผลเสร็จหรือยัง
> มีเอกสารไหนที่ประมวลผลไม่สำเร็จบ้าง

agent จะเรียก `lightrag_list_documents`

| ค่า | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `page` | `1` | หน้าที่ต้องการ |
| `page_size` | `20` | จำนวนเอกสารต่อหน้า (10–200) |
| `status` | ทุกสถานะ | แสดงเฉพาะเอกสารที่มีสถานะนี้: `processed` (พร้อมค้นหา) · `pending` `parsing` `analyzing` `processing` (กำลังประมวลผล) · `failed` (ประมวลผลไม่สำเร็จ) |

เอกสารเรียงจากใหม่ไปเก่า แต่ละรายการมีรหัส ชื่อ สถานะ วันที่เพิ่ม จำนวนตัวอักษร และเนื้อหาโดยย่อ เอกสารที่ประมวลผลไม่สำเร็จจะมี `error` บอกสาเหตุ (ดูตัวอย่างได้ที่[รูปแบบ JSON](#ดูรายการเอกสาร-lightrag_list_documents))

### 4. ลบเอกสารออกจากคลัง

เครื่องมือนี้**ปิดไว้เป็นค่าเริ่มต้น** เพราะเอกสารที่ลบแล้ว รวมทั้งเอนทิตีและความสัมพันธ์ที่สกัดจากเอกสารนั้น จะกู้คืนไม่ได้
หากต้องการให้ agent ลบเอกสารได้ ให้เพิ่ม `ENABLE_DELETE=true` ในไฟล์ `.env` แล้วสั่ง `docker compose up -d` และรีสตาร์ต agent เพื่อให้ agent เห็นเครื่องมือใหม่

ตัวอย่างคำสั่ง:

> ลบเอกสาร bbc-news-summary-18-10-2026 ออกจากคลังความรู้
> ลบเอกสารทุกฉบับที่ประมวลผลไม่สำเร็จ

agent จะเรียก `lightrag_delete` โดยคำอธิบายของเครื่องมือกำหนดให้ agent ยืนยันชื่อเอกสารกับผู้ใช้ก่อนลบทุกครั้ง

| ค่า | จำเป็น | ความหมาย |
|---|---|---|
| `documents` | ✓ | รายการเอกสารที่ต้องการลบ ระบุเป็นรหัส (ขึ้นต้นด้วย `doc-`) หรือชื่อเอกสาร ตามที่แสดงใน `lightrag_list_documents` หรือในแหล่งอ้างอิงของคำตอบ ระบุได้หลายรายการ |

- หากระบุเป็นชื่อ ระบบจะค้นหารหัสของเอกสารให้ แต่หากมีหลายเอกสารใช้ชื่อเดียวกัน ระบบจะไม่ลบและแจ้งรหัสทั้งหมดกลับมา เพื่อให้ระบุเป็นรหัสแทน
- ชื่อหรือรหัสที่ไม่พบจะแสดงใน `not_deleted` พร้อมเหตุผล
- สถานะ `deletion_started` แปลว่า LightRAG เริ่มลบในเบื้องหลังแล้ว
- สถานะ `busy` แปลว่า LightRAG กำลังประมวลผลเอกสารอื่นอยู่ จึงยังไม่ได้ลบ ให้ลองใหม่ภายหลัง

**การลบโดยไม่ผ่าน agent**
แม้ปิด `lightrag_delete` ไว้ ผู้ดูแลระบบยังลบเอกสารได้เสมอจาก WebUI ของ LightRAG ที่ `http://<เครื่องที่รัน LightRAG>:9621/webui` แท็บ Documents
(9621 คือพอร์ตเริ่มต้นของ LightRAG หากเปิดพอร์ตอื่นไว้ ให้เปลี่ยนตามนั้น) หรือเรียก API ของ LightRAG โดยตรง:

```bash
curl -X DELETE http://localhost:9621/documents/delete_document \
  -H "X-API-Key: <LIGHTRAG_API_KEY>" -H "Content-Type: application/json" \
  -d '{"doc_ids": ["doc-9db02b2c…"]}'
```

## รูปแบบ JSON ของคำขอและผลลัพธ์

mcp-lightrag มี 4 route

| Route | ใช้ทำอะไร |
|---|---|
| `POST /mcp` | เรียกเครื่องมือทั้งหมดตามมาตรฐาน MCP (JSON-RPC 2.0) agent ใช้ route นี้ |
| `GET /health` | ตรวจว่าเชื่อมต่อ LightRAG ได้และ LightRAG ยอมรับ key หรือไม่ ไม่ต้องใช้ token |
| `GET /usage` | ข้อมูลการใช้งาน: เวลาของการเรียกเครื่องมือทุกครั้ง และ token ของ LLM ที่ LightRAG เรียกผ่านมิเตอร์ (ใช้ token เดียวกับ `/mcp` หากกำหนด `MCP_AUTH_TOKEN`) |
| `/meter/…` | มิเตอร์ (ไม่บังคับ): ทางผ่านของการเรียก LLM และ embedding ของ LightRAG server เพื่อนับ token (ดู[ข้อมูลการใช้งาน](#ข้อมูลการใช้งาน-get-usage-และมิเตอร์)) |

### การส่งคำขอไปที่ `/mcp`

ทุกคำขอต้องมี header สองตัวนี้ (และ `Authorization: Bearer <token>` หากกำหนด `MCP_AUTH_TOKEN`)

```
Content-Type: application/json
Accept: application/json, text/event-stream
```

ผลลัพธ์จะส่งกลับในรูปแบบ Server-Sent Events คือมีบรรทัด `event: message` แล้วตามด้วย `data: <JSON>`
ตัวอย่างต่อไปนี้แสดงเฉพาะส่วน JSON และจัดบรรทัดใหม่ให้อ่านง่าย

ผลลัพธ์ของทุกเครื่องมืออยู่ใน `result.content[0].text` เป็นข้อความ สำหรับ `lightrag_list_documents` `lightrag_insert` และ `lightrag_delete` ข้อความนั้นเป็น JSON
ตัวอย่างด้านล่างจึงแสดงค่า `text` ในรูป JSON ที่แปลงกลับแล้ว เพื่อให้อ่านง่าย

### ดูรายการเครื่องมือ (`tools/list`)

คำขอ:

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
```

ผลลัพธ์ (ย่อ):

```json
{"jsonrpc": "2.0", "id": 1, "result": {"tools": [
  {
    "name": "lightrag_query",
    "description": "ค้นหาและสรุปคำตอบจากคลังความรู้ LightRAG …",
    "inputSchema": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "คำถามหรือหัวข้อที่ต้องการค้นหาในคลังความรู้"},
        "mode":  {"type": "string", "default": "hybrid", "enum": ["mix", "hybrid", "local", "global", "naive"]}
      },
      "required": ["query"]
    },
    "annotations": {"readOnlyHint": true, "openWorldHint": false}
  },
  {"name": "lightrag_list_documents", "…": "…"},
  {"name": "lightrag_insert", "…": "…"}
]}}
```

### ถามตอบ (`lightrag_query`)

คำขอ:

```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
  "name": "lightrag_query",
  "arguments": {"query": "VRAM ที่ต้องใช้สำหรับ LLM ขนาด 7B", "mode": "mix"}
}}
```

ผลลัพธ์ (คำตอบเป็นข้อความ Markdown):

```json
{"jsonrpc": "2.0", "id": 2, "result": {"isError": false, "content": [{"type": "text",
  "text": "… VRAM ขั้นต่ำประมาณ 5-6 GB …\n\n### References\n- [1] report_VRAM_LLM_local_17-10-2026"}]}}
```

### เพิ่มเอกสาร (`lightrag_insert`)

คำขอ:

```json
{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
  "name": "lightrag_insert",
  "arguments": {"text": "# รายงานประจำเดือน\nยอดขายเดือนตุลาคม …", "description": "monthly report 2026-10"}
}}
```

ค่า `text` ในผลลัพธ์:

```json
{
  "status": "success",
  "message": "Text successfully received. Processing will continue in background.",
  "track_id": "insert_20261019_100002_9ab1390f",
  "file_source": "monthly-report-2026-10"
}
```

`file_source` คือชื่อเอกสารที่บันทึกจริง ซึ่งใช้ระบุเอกสารนี้ตอนลบได้

### ดูรายการเอกสาร (`lightrag_list_documents`)

คำขอ:

```json
{"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
  "name": "lightrag_list_documents",
  "arguments": {"page": 1, "page_size": 20, "status": ""}
}}
```

ค่า `text` ในผลลัพธ์:

```json
{
  "pagination": {"page": 1, "page_size": 20, "total_count": 3, "total_pages": 1, "has_next": false, "has_prev": false},
  "status_counts": {"processed": 3, "all": 3},
  "documents": [
    {"id": "doc-9db02b2c032a71553ba9edc00386e506", "name": "bbc-news-summary-18-10-2026", "status": "processed",
     "created_at": "2026-10-18T04:33:14", "characters": 456,
     "summary": "# BBC News Summary - 18-10-2026 1. California Wildfires: …"}
  ]
}
```

เอกสารที่ประมวลผลไม่สำเร็จจะมี `"error": "<สาเหตุ>"` เพิ่มเข้ามา

### ลบเอกสาร (`lightrag_delete`, ต้องเปิด `ENABLE_DELETE=true`)

คำขอ (ระบุเป็นชื่อหรือรหัสก็ได้):

```json
{"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
  "name": "lightrag_delete",
  "arguments": {"documents": ["monthly-report-2026-10", "doc-9db02b2c032a71553ba9edc00386e506"]}
}}
```

ค่า `text` ในผลลัพธ์:

```json
{
  "lightrag": {"status": "deletion_started", "message": "Document deletion for 2 documents has been initiated. …",
               "doc_id": "doc-b2478b58…, doc-9db02b2c…"},
  "requested": {"monthly-report-2026-10": "doc-b2478b58…", "doc-9db02b2c032a71553ba9edc00386e506": "doc-9db02b2c…"},
  "not_deleted": {}
}
```

หากชื่อใดหาไม่พบหรือซ้ำกัน ชื่อนั้นจะอยู่ใน `not_deleted` พร้อมเหตุผล เช่น `{"twin": "2 documents share this name - delete by id: doc-ccc, doc-ddd"}`

### ข้อผิดพลาด

| กรณี | ผลลัพธ์ |
|---|---|
| ไม่ส่ง token หรือ token ผิด (เมื่อกำหนด `MCP_AUTH_TOKEN`) | HTTP 401 `{"error": "unauthorized"}` |
| เรียกเครื่องมือที่ไม่มีหรือปิดไว้ | `"isError": true` และ `text` เป็น `Unknown tool: lightrag_delete` |
| ไม่ส่งค่าที่จำเป็น | `"isError": true` และ `text` บอกชื่อค่าที่ขาด เช่น `text  Field required` |
| LightRAG ปฏิเสธ key | `text` เป็น `[LightRAG error HTTP 403 - check LIGHTRAG_API_KEY …]: …` |
| เชื่อมต่อ LightRAG ไม่ได้ | `text` เป็น `[LightRAG connection error: ConnectError - cannot reach LIGHTRAG_URL http://lightrag:9621]` |

### ตรวจสถานะ (`GET /health`)

```json
{
  "ok": true,
  "lightrag_url": "http://lightrag:9621",
  "key_configured": true,
  "lightrag": {"reachable": true, "key_accepted": true, "http_status": 200},
  "modes": ["mix", "hybrid", "local", "global", "naive"],
  "default_mode": "hybrid",
  "insert_enabled": true,
  "delete_enabled": false,
  "auth": false,
  "usage_log": {"enabled": true, "dir": "/app/usage", "writable": true, "last_error": null},
  "meter": {"enabled": true, "upstream": "https://openrouter.ai/api/v1"},
  "problems": []
}
```

เมื่อมีปัญหา `ok` จะเป็น `false` และ `problems` จะบอกสาเหตุพร้อมวิธีแก้ เช่น
`"LightRAG refused LIGHTRAG_API_KEY - it must match LIGHTRAG_API_KEY of the LightRAG server"`

### ข้อมูลการใช้งาน (`GET /usage`) และมิเตอร์

ระบบบันทึกการเรียกเครื่องมือทุกครั้งลงไฟล์ `usage-<วันที่>.jsonl` ใน docker volume `usage` เพื่อใช้วิจัยและปรับประสิทธิภาพ
ระเบียนมีเฉพาะเวลา ขนาด และจำนวน ไม่มีคำถาม คำตอบ หรือเนื้อหาเอกสาร

LightRAG ไม่รายงาน token ของ LLM ที่ตัวเองเรียก ทั้งที่คำถามหนึ่งข้อมักเรียก LLM 2 ครั้ง (สกัดคำสำคัญและเขียนคำตอบ) และ embedding 1 ครั้ง
และการเพิ่มเอกสารเรียก LLM อีกหลายครั้งเพื่อสกัดเอนทิตี หากต้องการนับ token เหล่านี้ ให้เปิด**มิเตอร์** ซึ่งเป็นทางผ่านให้ LightRAG เรียกผู้ให้บริการผ่าน mcp-lightrag

1. ในไฟล์ `.env` ของ mcp-lightrag กำหนด endpoint จริงของผู้ให้บริการ แล้วสั่ง `docker compose up -d`

   ```bash
   METER_UPSTREAM=https://openrouter.ai/api/v1
   ```

2. ในไฟล์ `.env` ของ LightRAG server เปลี่ยนที่อยู่ของ LLM และ embedding ให้ชี้มาที่มิเตอร์ แล้วรีสตาร์ต LightRAG

   ```bash
   LLM_BINDING_HOST=http://mcp-lightrag:8700/meter
   EMBEDDING_BINDING_HOST=http://mcp-lightrag:8700/meter
   ```

มิเตอร์ส่งทุกคำขอต่อไปยัง `METER_UPSTREAM` โดยไม่แก้ไขอะไร และใช้ API key ของ LightRAG เอง (mcp-lightrag ไม่เก็บ key นี้)
มิเตอร์เรียกได้เฉพาะ `METER_UPSTREAM` จึงไม่ใช่ proxy เปิดที่ใครก็ใช้ได้ ข้อควรรู้คือเมื่อเปิดมิเตอร์ LightRAG จะเรียก LLM ได้เฉพาะตอนที่ mcp-lightrag ทำงานอยู่
หากต้องการเลิกใช้ ให้เปลี่ยน `LLM_BINDING_HOST` และ `EMBEDDING_BINDING_HOST` กลับเป็นที่อยู่เดิมของผู้ให้บริการ

ผลลัพธ์ของ `GET /usage` (ย่อ) หลังถามหนึ่งข้อขณะเปิดมิเตอร์:

```json
{
  "schema": "harness-usage/1",
  "environment": {"component": "mcp-lightrag", "version": "0.4.0", "host": "8b1c…", "cpu_count": 20, "mem_total_mb": 11816, "…": "…"},
  "records": [
    {"component": "lightrag", "kind": "llm_call", "tool": "lightrag-server", "model": "google/gemma-4-31b-it",
     "duration_s": 3.425, "input_tokens": 691, "output_tokens": 34, "cost_usd": 8.066e-05, "status": "ok",
     "detail": {"via": "meter", "http_status": 200, "request_chars": 2817, "response_chars": 913, "stream": false}},
    {"component": "lightrag", "kind": "embedding_call", "model": "Qwen/Qwen3-Embedding-8B", "duration_s": 2.305,
     "input_tokens": 20, "output_tokens": 0, "cost_usd": 2e-07, "detail": {"via": "meter", "inputs": 1, "…": "…"}},
    {"component": "lightrag", "kind": "llm_call", "duration_s": 10.209, "input_tokens": 4685, "output_tokens": 604,
     "cost_usd": 0.00067386, "status": "ok"},
    {"component": "mcp-lightrag", "kind": "mcp_tool", "tool": "lightrag_query", "duration_s": 16.583, "status": "ok",
     "detail": {"mode": "mix", "query_chars": 23, "result_chars": 2210}}
  ]
}
```

- `component` `mcp-lightrag` คือการเรียกเครื่องมือของ agent ส่วน `lightrag` คือการเรียก LLM และ embedding ของ LightRAG server ผ่านมิเตอร์
- การเรียกของ LightRAG ที่เกิดระหว่างการเรียกเครื่องมือหนึ่งครั้ง (ช่วงเวลาซ้อนกัน) คือส่วนหนึ่งของคำถามนั้น ส่วนที่เกิดภายหลัง เช่น การสร้างดัชนีหลัง `lightrag_insert` คืองานเบื้องหลัง
- LightRAG ตอบจาก cache ได้ (`llm_response_cache`) คำถามที่เคยถามแล้วจึงอาจไม่มีการเรียก LLM เลย
- ชื่อช่องข้อมูลเป็นแบบเดียวกับ plugin `usage-telemetry` ของ [osint-harness-profile](https://github.com/chacharin/osint-harness-profile) และ MCP ตัวอื่นของชุดนี้

| ค่าของ `GET /usage` | ความหมาย |
|---|---|
| `since`, `until` | ช่วงเวลา (epoch วินาที) หากไม่ระบุจะส่งทั้งหมด |
| `limit` | จำนวนระเบียนสูงสุด (ล่าสุด) ค่าเริ่มต้น 50000 |

### ทดลองด้วย curl

```bash
curl http://127.0.0.1:8806/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"lightrag_query","arguments":{"query":"สรุปเอกสารในคลัง","mode":"hybrid"}}}'
```

บน Windows คำสั่ง curl อาจส่งภาษาไทยที่พิมพ์ในบรรทัดคำสั่งผิดเพี้ยนเป็น `?` ให้บันทึก JSON ของคำขอเป็นไฟล์ UTF-8 เช่น `request.json` แล้วส่งด้วย `-d @request.json` แทน

## การปรับให้เหมาะกับคลังของคุณ

ค่าต่อไปนี้เป็นตัวแปรในไฟล์ `.env` ซึ่งไม่จำเป็นต้องกำหนด หากไม่กำหนด ระบบจะใช้ค่าเริ่มต้น
เมื่อต้องการปรับ ให้เพิ่มบรรทัด `ชื่อตัวแปร=ค่า` ลงในไฟล์ `.env` แล้วสั่ง `docker compose up -d` (คำอธิบายและค่าเริ่มต้นของทุกตัวแปรดูได้ใน [`.env.example`](.env.example))

- **`KB_DESCRIPTION`** อธิบายสั้น ๆ ว่าคลังเก็บเอกสารเรื่องอะไร เช่น `คู่มือและนโยบายภายในของบริษัท` ระบบจะใส่ข้อความนี้ในคำอธิบายเครื่องมือ เพื่อให้ agent ตัดสินใจได้ว่าคำถามใดควรค้นจากคลังนี้
- **`QUERY_MODES` และ `DEFAULT_MODE`** กำหนดวิธีค้นหาที่ให้ agent เลือก และวิธีที่ใช้เมื่อ agent ไม่ได้ระบุ
- **`QUERY_EXTRA_PARAMS`** ส่งค่าอื่นของ LightRAG ไปกับทุกการค้นหา เช่น `{"top_k": 40, "response_type": "Bullet Points"}`
- **`ENABLE_INSERT` และ `ENABLE_DELETE`** กำหนดว่า agent เพิ่มหรือลบเอกสารได้หรือไม่
- **`USAGE_LOG`, `USAGE_DIR` และ `METER_UPSTREAM`** การบันทึกข้อมูลการใช้งาน และมิเตอร์สำหรับนับ token ของ LightRAG

## ความปลอดภัย

ระบบนี้มีจุดที่ต้องป้องกัน 2 ชั้น

1. **mcp-lightrag → LightRAG** ใช้ `LIGHTRAG_API_KEY` ซึ่ง**จำเป็นต้องกำหนด** หากเว้นว่าง ระบบจะไม่เริ่มทำงาน
   เพราะ LightRAG ที่ไม่มี key จะให้ทุกคนที่เข้าถึงพอร์ตของ LightRAG อ่าน เพิ่ม และลบเอกสารได้โดยตรง
   ควรใช้ key ที่สุ่มและยาวอย่างน้อย 32 ตัวอักษร ไม่ใช่ค่าที่เดาง่าย เช่น `1234` สร้างได้ด้วยคำสั่ง
   `python -c "import secrets; print(secrets.token_urlsafe(32))"` แล้วใส่ค่าเดียวกันทั้งใน LightRAG server และในไฟล์ `.env` ของ mcp-lightrag
2. **agent หรือเครื่องอื่น → mcp-lightrag** (พอร์ต 8806) ผู้ที่เรียกผ่านพอร์ตนี้ได้จะใช้คลังความรู้ได้โดยไม่ต้องรู้ key ของ LightRAG
   จึงต้องปิดชั้นนี้ด้วย ตามรายละเอียดด้านล่าง

- **ค่าเริ่มต้นไม่มีการยืนยันตัวตน** และเปิดให้เครื่องอื่นในเครือข่ายเข้าถึงได้ (`PUBLISH_ADDR=0.0.0.0`) ผู้ที่เข้าถึงพอร์ตนี้ได้จะค้นหาและเพิ่มเอกสารในคลังได้ทันที รวมทั้งลบเอกสารได้หากเปิด `ENABLE_DELETE`
  หากไม่จำเป็น ให้กำหนด `PUBLISH_ADDR=127.0.0.1` ซึ่ง agent ที่อยู่ใน docker network เดียวกันจะยังเรียกใช้ได้ตามปกติ หรือกำหนด `MCP_AUTH_TOKEN` เพื่อบังคับให้ผู้เรียกต้องส่ง token
- เปิด `ENABLE_DELETE` เฉพาะเมื่อจำเป็น และควรสำรองข้อมูลของ LightRAG ไว้ก่อน
- API key ของ LightRAG ถูกเก็บไว้ในไฟล์ `.env` เท่านั้น ไม่ถูกส่งให้ agent และไฟล์นี้จะไม่ถูกส่งขึ้น git
- มิเตอร์ (`/meter/…`) ไม่ต้องใช้ `MCP_AUTH_TOKEN` เพราะ LightRAG ส่ง key ของผู้ให้บริการมาเอง ผู้ที่เรียกมิเตอร์ได้ต้องมี key ของผู้ให้บริการอยู่แล้ว และเรียกได้เฉพาะ `METER_UPSTREAM` หากไม่ใช้มิเตอร์ ให้เว้น `METER_UPSTREAM` ว่างไว้ (ค่าเริ่มต้น)

## สำหรับนักพัฒนา

โค้ดหลักอยู่ในโฟลเดอร์ `app/`

| ไฟล์ | หน้าที่ |
|---|---|
| `config.py` | อ่านและตรวจสอบการตั้งค่าจาก `.env` |
| `lightrag.py` | เรียก REST API ของ LightRAG และจัดรูปแบบผลลัพธ์ |
| `server.py` | MCP server เครื่องมือทั้งหมด `/health`, `/usage` และการตรวจ token |
| `usage.py` | บันทึกและอ่านข้อมูลการใช้งาน |
| `meter.py` | มิเตอร์: ส่งการเรียก LLM ของ LightRAG ต่อไปยังผู้ให้บริการ และบันทึก token |

ชุดทดสอบจำลอง LightRAG ด้วย `httpx.MockTransport` จึงไม่ต้องมี LightRAG จริงและไม่เสียค่าใช้จ่าย สั่งทดสอบผ่าน Docker ได้โดยไม่ต้องติดตั้ง Python:

```bash
docker run --rm -v "$PWD:/w" -w /w -e UV_PROJECT_ENVIRONMENT=/tmp/venv python:3.12-slim \
  sh -c "pip install -q uv==0.13.1 && uv run --frozen pytest -q -p no:cacheprovider"
```

ไลบรารีทุกตัวถูกล็อกเวอร์ชันไว้ใน `uv.lock` หากแก้ `pyproject.toml` ให้เปลี่ยน `uv run --frozen pytest ...` ในคำสั่งข้างต้นเป็น `uv lock` แล้ว commit ไฟล์ `uv.lock` ที่เปลี่ยนไป
หากใช้ PowerShell ให้เปลี่ยน `$PWD` เป็น `${PWD}` และใช้ `` ` `` แทน `\` สำหรับขึ้นบรรทัดใหม่

## สัญญาอนุญาต

[MIT](LICENSE) © 2026 Chacharin Lertyosbordin
LightRAG เป็นลิขสิทธิ์ของ HKUDS ภายใต้สัญญาอนุญาต MIT ([ซอร์สโค้ด](https://github.com/HKUDS/LightRAG))
