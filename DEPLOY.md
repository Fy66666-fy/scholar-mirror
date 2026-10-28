# 部署说明

两种线上形态，任选其一。仓库已推到 GitHub：
`https://github.com/Fy66666-fy/scholar-mirror`

---

## 一、Streamlit Community Cloud（推荐，免费）

### 1. 建应用

1. 打开 <https://share.streamlit.io>，用 GitHub 账号登录
2. **New app** → 选仓库 `Fy66666-fy/scholar-mirror`、分支 `main`、主文件 `app.py`
3. 点 **Advanced settings**

### 2. 关键设置（一定要做）

**Python 版本**：3.11 或 3.12（3.13 部分依赖尚未预编译）。

**Secrets** 填下面两行：

```toml
public_demo = true
```

这一项决定访客之间会不会互相污染数据：

| `public_demo` | 行为 |
|---|---|
| `true`（推荐） | 每个浏览器会话一个独立 SQLite（`data/sessions/<session>.db`），新会话自动载入 12 篇演示文献 + 示例画像 + 示例项目；最多保留 40 个会话库，超出自动清理 |
| 未设置 | 所有访客共用同一个库，A 的收藏会出现在 B 的文献库里 —— 只适合自己用 |

本地开发不受影响：不设这个变量就是普通单用户模式。

### 3. 首次访问

打开分享链接后会直接进入「工作台」，里面已经有一套演示数据（书架「演示数据」、项目「示例项目」）。
访客可以正常检索、收藏、建项目；关闭页面后该会话的库会在后续清理中被删除。

### 4. 注意事项

- 免费实例会休眠：一段时间无人访问后首次打开需等 30–60 秒唤醒。
- 容器文件系统是临时的：实例重启后所有会话数据清空，演示数据会重新生成。
- 检索会真实访问 OpenAlex / Crossref / arXiv / PubMed / Europe PMC，需要出网；单源失败会自动降级。
- arXiv 有 3 秒/次的硬限速，第一次检索慢几秒是正常的。

---

## 二、自建服务器 / Docker

```bash
git clone https://github.com/Fy66666-fy/scholar-mirror.git
cd scholar-mirror
pip install -r requirements.txt

# 单用户
streamlit run app.py --server.port 8601 --server.address 0.0.0.0

# 公开演示（每会话独立库）
SM_PUBLIC_DEMO=1 python serve.py        # 读取 $PORT，默认 8601
```

`serve.py` 只是把 Streamlit 挂到 `$PORT` 并打开会话隔离，方便容器平台直接使用：

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8080 SM_PUBLIC_DEMO=1
CMD ["python", "serve.py"]
```

---

## 三、数据与隐私

- 所有文献、画像、项目、笔记都在容器内的 SQLite 里，不上传到任何第三方。
- 唯一的出网请求是检索：把关键词发给六个公开文献接口（免注册、无账号）。
- 公开演示模式下，服务端不记录访客身份，也不做行为埋点。
- 需要长期保存数据时，用「设置 → 数据与缓存 → 下载数据库备份」导出 `mirror.db`。
