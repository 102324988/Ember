# 数据持久化与时空修复

后端请使用项目的 Conda `Ember` 环境，执行 `pip install -r requirements.txt`，再运行 `python server.py`。前端仍使用 `cd frontend`、`npm run dev`。`run_all.bat` 保留原有启动方式。

## 数据库与回退

- Docker PostgreSQL 对外端口为 `127.0.0.1:5433`，容器内仍为 5432；本机 PostgreSQL 的 5432 不变。
- `.env` 中的 `PG_HOST`、`PG_PORT` 指向 Docker，Compose 使用相同的 `PG_PASSWORD`。已有数据库卷不会因修改环境变量自动更换密码；本次已经同步实际用户密码。
- 本次迁移前备份位于 `data/backups/repair_20261008_164619/`，包含原配置、角色状态、短期记忆及数据库记录。`migration_report.json` 记录逐行核对结果。该目录及所有凭据均被 Git 忽略。
- 本机源数据库保留原始数据。回退前应先导出 Docker 中迁移后新增的数据，再恢复备份中的 `.env` 和 Compose 配置；不要删除数据库卷。原本机数据库缺少向量扩展，回退连接后长期记忆仍会报告不可用。
- `python utils/migrate_postgres.py <备份目录>/database.json` 只允许向空目标库迁移；目标业务表已有数据时中止，不能重复覆盖。
- 消息和长期记忆写入失败分别保存在 `data/failed_writes/`、`data/failed_memories/`。启动时重放，稳定标识防止重复；存读档会拒绝带未保存任务继续运行。

## 时间、场景与接口

- 默认 `TIMEZONE=Asia/Shanghai`，`START_TIME=` 表示现实时间；`?` 延续上次状态，也支持 ISO 时间。无效格式记录配置警告。读档恢复存档时间。
- 心跳间隔、空闲阈值按真实秒数判断，时间加速只影响逻辑时钟。正常启动先处理旧场景；不能确认时降级为“活动待确认”。
- 对话先准备状态再生成回复。状态包含 `scene`（角色位置、用户位置、交流方式及远程联系方式）、`state_source`、`scene_status`。旧场景只能恢复角色位置；用户位置未知时不会假定同处一地。
- 新短期消息包含逻辑时间戳；旧消息标记时间未知。历史中的“明天、晚安”不能证明当前事实；纯独白不会成为对白。
- `/history` 保持成功数组格式，新增 `message_id`；支持 `before` 与 `before_id` 联合分页，故障返回 HTTP 503。WebSocket 使用同一消息标识，最终回复会替换中间工具文本。
- `/config.status` 提供数据库、长期记忆、场景准备、暂停及配置警告。前端显示历史错误、自动重试，并在重连时合并历史。
- 前端可通过 `VITE_API_BASE_URL` 指定后端地址；默认 `http://localhost:8000`。

## 验证

`python -m pytest tests -q` 自动创建 `ember_test_*` 临时数据库并使用临时配置；测试关闭生产 Neo4j 连接，结束后删除测试数据库。创建数据库失败会中止测试，不会退回业务库。

前端执行 `npm run build` 和 `node --test tests/history.test.mjs`。

`python utils/validate_live.py` 会调用当前配置的模型接口并产生少量用量，但只使用脚本内合成场景与空历史，不读取现有聊天、角色状态或人设。结果保存在 `data/backups/live_validation.json`；合成模型输出保存在 `live_validation_debug.json`。
