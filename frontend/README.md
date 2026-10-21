# Ember 前端

React + Vite + Pixi/Live2D。默认舞台优先，可切换对话优先；聊天、声音、历史、场景与设置分别管理。

## 开发

```powershell
npm install
npm run dev
```

默认后端 `http://localhost:8000`，使用 `VITE_API_BASE_URL` 配置。开发端口默认 5173。同步更新并重启后端，以启用消息确认与指定消息重播。

## 检查

```powershell
npm run lint
npm test
npm run build
npm run test:browser
```

浏览器检查需要 Playwright 与 Chromium。已有外部安装时可设置 `PLAYWRIGHT_MODULE_PATH` 和 `PLAYWRIGHT_CHROMIUM_EXECUTABLE`；否则在开发工具环境安装 Playwright 后运行。

浏览器检查自行启动临时 Vite，强制合成 API、聊天和音频，不启动或访问真实后端。覆盖输入法、草稿、发送确认、播放控制、历史分页及错误恢复、弹窗、窄屏和模型加载恢复。截图在 `test-results/`，不提交 Git。

后端的模拟协议检查可在项目根目录执行 `python utils/validate_ui_protocol.py`。完整隔离数据库测试仍为 `python -m pytest tests -q`，要求 Docker PostgreSQL 已就绪。

## 模块

- `App.jsx`：应用布局、草稿和界面偏好。
- `useEmberSession.js`：连接、配置同步、历史与消息收据。
- `messageHistory.js`：消息合并与对白解析。
- `audioController.js`：唯一声音队列、静音和指定请求重播。
- `components/ChatPanel.jsx`：聊天展示、阅读锚点与分页。
- `components/Modal.jsx`：原生模态弹窗。
- `Live2DViewer.jsx`：容器驱动角色显示与口型。
- `ArchiveModal.jsx`：现有存档工作流。

完整规划见 `../docs/frontend-experience-plan.md`，第一阶段交付、验证限制和回退说明见 `../docs/frontend-phase-one.md`。

轮次控制见 `../docs/frontend-turn-control.md`。停止生成需配套新后端；停止确认前可以保留/编辑草稿，并可取消待发消息。数据库启动时补齐中断状态字段。
