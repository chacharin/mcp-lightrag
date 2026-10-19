# mcp-lightrag

MCP server ที่ช่วยให้ AI agent ที่รองรับ MCP เช่น Hermes ค้นหาและเพิ่มเอกสารในคลังความรู้ [LightRAG](https://github.com/HKUDS/LightRAG) ได้โดยตรง
ทำงานบน Docker ในโหมด **streamable HTTP** โดย agent ไม่ต้องรู้ API key ของ LightRAG

ผู้พัฒนา: **Chacharin Lertyosbordin**

> โปรเจกต์นี้เป็นตัวกลางระหว่าง agent กับ LightRAG server เท่านั้น ไม่ได้รวม LightRAG มาด้วย
> LightRAG พัฒนาโดย HKUDS ภายใต้สัญญาอนุญาต MIT และโปรเจกต์นี้ไม่ใช่ผลงานทางการของทีม LightRAG

## เครื่องมือที่มีให้

| เครื่องมือ | API ของ LightRAG ที่ใช้ | หน้าที่ |
|---|---|---|
| `lightrag_query` | `POST /query` | ค้นหาและสรุปคำตอบจากคลังความรู้ พร้อมระบุเอกสารที่ใช้อ้างอิง agent เลือกวิธีค้นหาได้ (`mix` `hybrid` `local` `global` `naive`) |
| `lightrag_insert` | `POST /documents/text` | เพิ่มข้อความ รายงาน หรือสรุปเข้าคลัง โดยตั้งชื่อเอกสารตามที่ agent ระบุ หรือตามวันและเวลาหากไม่ระบุ |

หากต้องการให้ agent ค้นหาได้อย่างเดียว ให้กำหนด `ENABLE_INSERT=false` ระบบจะไม่แสดงเครื่องมือ `lightrag_insert` ให้ agent เห็น

## หลักการทำงาน

```
agent ──POST /mcp──▶ mcp-lightrag (container)
                       ① ตรวจ token หากกำหนด MCP_AUTH_TOKEN ไว้
                       ② ส่งคำถามหรือเอกสารไปยัง LightRAG พร้อม LIGHTRAG_API_KEY
                     ◀── ส่งคำตอบและรายชื่อเอกสารอ้างอิงกลับไปยัง agent
```

LightRAG ใช้ LLM สรุปคำตอบทุกครั้งที่ค้นหา และใช้ LLM สกัดเอนทิตีทุกครั้งที่เพิ่มเอกสาร ค่าใช้จ่ายจึงขึ้นอยู่กับ LLM ที่ตั้งไว้ใน LightRAG server
ส่วน mcp-lightrag ไม่เก็บสถานะการทำงาน ไม่มีฐานข้อมูล และไม่ต้อง mount โฟลเดอร์ใด ๆ

## เริ่มต้นใช้งาน

### สิ่งที่ต้องเตรียม

- **Docker** (Docker Desktop หรือ Docker Engine)
- **LightRAG server** ที่ทำงานอยู่แล้ว ([วิธีติดตั้ง](https://github.com/HKUDS/LightRAG#install-lightrag-server)) และอยู่ใน docker network เดียวกับ agent
- **API key ของ LightRAG** คือค่า `LIGHTRAG_API_KEY` ที่ตั้งไว้ใน LightRAG server (หาก LightRAG ไม่ได้ตั้ง key ไว้ ให้เว้นว่าง)

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

### การปรับให้เหมาะกับคลังของคุณ

- **`KB_DESCRIPTION`** อธิบายสั้น ๆ ว่าคลังเก็บเอกสารเรื่องอะไร เช่น `คู่มือและนโยบายภายในของบริษัท` ระบบจะใส่ข้อความนี้ในคำอธิบายเครื่องมือ เพื่อให้ agent ตัดสินใจได้ว่าคำถามใดควรค้นจากคลังนี้
- **`QUERY_MODES` และ `DEFAULT_MODE`** กำหนดวิธีค้นหาที่ให้ agent เลือก และวิธีที่ใช้เมื่อ agent ไม่ได้ระบุ
- **`QUERY_EXTRA_PARAMS`** ส่งค่าอื่นของ LightRAG ไปกับทุกการค้นหา เช่น `{"top_k": 40, "response_type": "Bullet Points"}`

## การเชื่อมต่อกับ MCP client

ตัวอย่างการตั้งค่าใน Hermes (`config.yaml`):

```yaml
mcp_servers:
  lightrag:
    url: http://mcp-lightrag:8700/mcp
    timeout: 180        # ควรนานกว่า QUERY_TIMEOUT_SECONDS (ค่าเริ่มต้น 120 วินาที)
```

หากกำหนด `MCP_AUTH_TOKEN` ไว้ ให้เพิ่ม header `Authorization: Bearer <token>` ในการตั้งค่าของ client ด้วย
สำหรับ client ที่อยู่นอก docker network ให้ใช้ `http://<IP ของเครื่อง>:8806/mcp`

## ความปลอดภัย

- **ค่าเริ่มต้นไม่มีการยืนยันตัวตน** และเปิดให้เครื่องอื่นในเครือข่ายเข้าถึงได้ (`PUBLISH_ADDR=0.0.0.0`) ผู้ที่เข้าถึงพอร์ตนี้ได้จะค้นหาและเพิ่มเอกสารในคลังได้ทันที
  หากไม่จำเป็น ให้กำหนด `PUBLISH_ADDR=127.0.0.1` ซึ่ง agent ที่อยู่ใน docker network เดียวกันจะยังเรียกใช้ได้ตามปกติ หรือกำหนด `MCP_AUTH_TOKEN` เพื่อบังคับให้ผู้เรียกต้องส่ง token
- หากไม่ต้องการให้ agent แก้ไขคลัง ให้กำหนด `ENABLE_INSERT=false`
- API key ของ LightRAG ถูกเก็บไว้ในไฟล์ `.env` เท่านั้น ไม่ถูกส่งให้ agent และไฟล์นี้จะไม่ถูกส่งขึ้น git

## สำหรับนักพัฒนา

โค้ดหลักอยู่ในโฟลเดอร์ `app/`

| ไฟล์ | หน้าที่ |
|---|---|
| `config.py` | อ่านและตรวจสอบการตั้งค่าจาก `.env` |
| `lightrag.py` | เรียก REST API ของ LightRAG และจัดรูปแบบคำตอบ |
| `server.py` | MCP server เครื่องมือทั้งสอง `/health` และการตรวจ token |

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
