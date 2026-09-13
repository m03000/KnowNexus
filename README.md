# KnowNexus

本地优先的 Windows AI 知识工作台，当前版本仅为初步设计版本，如有问题，请向作者反馈。

### 下载 ZIP，解压即用

KnowNexus 将 AI 对话、长期记忆、个人笔记、文档学习、代码解析、Obsidian Wiki 与知识星图整合到一个桌面应用中,应用自动启动并管理本地后端。

> 当前版本：**0.1.0**  
> 项目处于早期开发阶段，界面、接口与数据结构仍可能调整。

## 下载与启动

前往 [GitHub Releases](https://github.com/m03000/KnowNexus/releases) 下载：

`KnowNexus-0.1.0-Windows-x64-portable.zip`

使用步骤：

1. 将 ZIP 完整解压到一个固定目录，例如 `D:\Apps\KnowNexus`。
2. 双击根目录中的 `KnowNexus.exe` 启动。
3. 首次启动后，根据“必要配置”提示设置模型服务并下载本地检索模型。
4. releases中包含已经下载好的OCR/Whisper等多模态组件
   
当前公开版本尚未进行商业代码签名，因此 Windows SmartScreen 首次运行时可能显示“未知发布者”。请确认文件来自本仓库的 Release 页面后再运行。

## 首次配置

### 模型服务

打开：

```text
设置 → 模型服务
```

填写配置名称、API Key、Base URL 和模型名称，然后保存并设为当前模型。KnowNexus 支持 OpenAI 兼容接口。


### 本地检索模型

便携版默认在`data` 存放数据库、笔记、设置和桌面缓存，`logs` 存放日志，`model` 存放模型。  
也可在启动前设置环境变量 `KNOWNEXUS_STORAGE_ROOT` 指定数据根目录。  
迁移旧版本时，请先完全退出托盘程序；旧数据不会自动删除或导入。
“测试模型”会离线加载权重并实际生成向量或进行重排评分；测试不会下载文件。  
“已安装”表示检测到所需文件，测试成功才确认当前电脑可以加载和运行模型。

打开：

```text
设置 → 基础配置 → 本地检索模型
```

分别下载：

- Embedding：`BAAI/bge-m3`
- Reranker：`cross-encoder/ms-marco-MiniLM-L-6-v2`

这两个 RAG 模型不包含在 ZIP 中，由用户首次使用时按需下载。  
下载时会优先连接 Hugging Face 官方源；仅在官方源发生网络连接错误时，自动改用备用镜像重试一次。已经下载的文件会保留在本机缓存中。  
未下载时软件仍能启动，但本地知识检索、召回和排序功能无法完整工作。

### Obsidian Wiki / MCP

如需使用自己的 Obsidian Vault：

1. 进入“设置 → 基础配置 → Obsidian Wiki / MCP”。
2. 创建 Vault 配置并填写名称。
3. 选择本地 Vault 目录。
4. 保存并设为当前 Vault。
5. 点击测试，确认连接成功后启用。

这样 KnowNexus 会调用 Obsidian MCP 来创建您的LLM Wiki，  
不使用 Obsidian 时，也可以继续使用 KnowNexus 内置的本地 Wiki，但此时维护的 LLM Wiki 仅为简单Wiki。

## 文档

普通用户可以按照以下顺序了解软件：

| 目标 | 本页位置 |
| --- | --- |
| 下载并启动 | [下载与启动](#下载与启动) |
| 完成首次配置 | [首次配置](#首次配置) |
| 了解各个界面 | [主要功能](#主要功能) |
| 查找数据位置 | [数据与隐私](#数据与隐私) |
| 解决启动与模型问题 | [常见问题](#常见问题) |
| 从源码运行 | [开发](#开发) |


## AI 对话

连接 OpenAI 兼容模型服务，在本地桌面中创建和管理会话，对话可作为后续记忆整理和知识关联的来源。  
你可以将抖音、b站等第三方平台的链接交给它，从而生成 AI 笔记，这些笔记会自动进入 LLM Wiki 维护成您的知识体系。  
也可以让它根据本地知识库查询过往记忆和知识内容。

### 对话功能1：代码项目解析

代码项目功能可以扫描本地项目，展示目录、文件、类、函数、原始代码、代码块说明与项目关系，  
但当前项目解析功能并不完善，仅能解析核心重点文件，待后续开发。
如左侧没有代码项目入口，先点击“添加界面”并启用代码项目。  
大型项目首次解析可能耗时较长，建议排除依赖、缓存和构建产物。

### 对话功能2：外部平台链接解析（默认生成笔记）

在对话中给定平台链接，比如抖音b站链接；  
它会读取这个链接的视频内容并根据内容生成ai笔记，自动进入LLM Wiki知识体系。   
但是读取平台链接必须满足以下配置前提：
```text
设置 → 基础配置 → 平台视频凭证
```
在平台视频凭证中导入cookies.txt，获取cookies.txt具体流程如下：
- 在Chroma或者Edge浏览器中点击扩展/扩展程序
- 搜索`Get cookies.txt LOCALLY`并安装
- 打开抖音或 B站并登录，保证已经显示头像
- 打开`Get cookies.txt LOCALLY`并导出当前网站 Cookie（Export）
- 浏览器会下载一个 .txt 文件，保证第一行为`# Netscape HTTP Cookie File`
- 在基础配置里面导入它即可正常让KnowNexu根据你提供的链接生成笔记

## 外部智能体监听

支持 Codex、WorkBuddy 等会话来源，会实时将您的外部智能体的对话记录记录到 KnowNexus 中，构建自己的共享记忆库。  
所有记忆会经过蒸馏环节形成原文-事实-关联三类结构，供 KnowNexus 快速查询与外部智能体知识检索的 MCP 服务。

启用前建议：

1. 在“设置 → 外部智能体监听”选择正确的适配器。
2. 填写会话正文、会话索引或辅助记忆路径。
3. 先使用“测试监听”检查解析预览。
4. 确认内容和路径正确后再开启监听。

注意：关闭监听只会停止后续读取，不会自动删除已经生成的记忆。  
监听功能仅查看您的记忆文件，不会对文件本身进行修改，您可以询问ai记忆文件位置再填入

### 监听服务：MCP 检索：

若想实现跨智能体的记忆共享，请为你的智能体连接 KnowNexus 的MCP服务。  
KnowNexus 内置了一个基于 Streamable HTTP 的 MCP 服务。  
其他支持 MCP 的智能体可以通过它检索 KnowNexus 中的代码、笔记和长期记忆。

- 先启动 `KnowNexus.exe`，并保持程序在运行状态。
- 关闭主窗口后，KnowNexus 会驻留系统托盘，MCP 服务也会继续运行。   
  只有从托盘菜单中选择“退出 KnowNexus”，本地 MCP 服务才会停止。
- 浏览器中访问以下地址检查后端是否正常：  
  http://127.0.0.1:8765/health  
  如果返回 status: ok，说明本地后端已经启动
- 在支持远程 HTTP MCP 的智能体中新增一个服务(不同智能体使用的配置字段可能略有区别，但核心信息相同)：
```text
 {
   "mcpServers": {
     "knownexus": {
       "url": "http://127.0.0.1:8765/mcp/"
     }
   }
 }
```  
以codex为例：
- 打开 Codex 配置文件：   
  %USERPROFILE%\.codex\config.toml
- 加入：
  ```text
  [mcp_servers.knownexus]
  url = "http://127.0.0.1:8765/mcp/"
  enabled = true
  required = false
  default_tools_approval_mode = "writes"
  
  enabled_tools = [
    "search_personal_knowledge",
    "trace_memory",
    "capture_external_turn",
    "flush_external_memory",
  ]
  
  [mcp_servers.knownexus.tools.search_personal_knowledge]
  approval_mode = "approve"
  
  [mcp_servers.knownexus.tools.trace_memory]
  approval_mode = "approve"
  ```
- 保存配置后重新启动 Codex。

其中便携桌面版的 MCP 地址是：

```text
http://127.0.0.1:8765/mcp/
```

## 笔记与文档

可以导入和阅读 Markdown、TXT、HTML、Office 文档、PDF等资料。
- 图片与扫描 PDF 使用随包提供的 Tesseract OCR。
- 导入文件后下面会弹出是否进入 LLM Wiki， 统一则会自动进入您的知识体系

## 知识星图

KnowNexus 提供记忆星图、笔记星图和项目星图：

基础通用功能：
- 单击节点：聚焦当前节点和关联节点。
- 拖动空白区域：移动视图。
- 使用滚轮：缩放视图。
- 使用搜索框或目录：定位节点。
- 关联数量较多时仍显示全部节点和连线，但只展示固定数量的节点名称，避免标签重叠。
- 记忆星图仅供基础展览，后续会尝试优化新的功能

记忆抽屉与记忆信息：
- 记忆抽屉界面会显示所有的事实、决定、进行中、变化的记忆卡片，  
  可以查看这些卡片的关联与关键词关联卡片。
- 记忆信息会显示所有记忆点与关联，并直观展示所有相关星点，可以在此处快捷查看所有记忆

## 其他功能

### LLM Wiki 与热点

仪表盘的 Wiki 区域用于查看当前 Vault、文档数量、概念、主题、热点和构建消耗。  
热点内容可以阅读并加入 LLM Wiki，兴趣主题可以在界面中维护。

### 主题、壁纸和磨砂玻璃

界面支持浅色、深色和壁纸三种表现。  
用户可以上传图片或视频壁纸，并从保存在本地的壁纸库中重新选择（注意，当前仅测试了开发者使用的壁纸，无法完美适配所有壁纸，如出现观感不好的效果，请见谅）。   
设置中可以调整壁纸模糊、边框、卡片透明度和磨砂玻璃强度，也可以分别控制仪表盘、对话、笔记目录、代码目录和星图信息区域。  
不同主题使用相同的布局、字号与尺寸，主要区别是颜色和背景表现。

## 数据与隐私

便携版用户数据默认保存在：

```text
KnowNexus.exe 所在目录\data
```

通常对应：

```text
D:\github\KnowNexus-portable\data
```

其中可能包含数据库、日志、模型服务配置、壁纸、下载的检索模型、Wiki、记忆和文档处理数据。

KnowNexus 以本地存储为主，但向 AI 提问时，消息会发送给用户自己配置的模型服务商。启用外部智能体监听前，也请确认所选目录中不存在不希望处理的敏感内容。

新版数据跟随程序目录。更新时保留 `data`、`model` 和 `logs`，不要随旧程序一起删除。旧版 `%APPDATA%\KnowNexus` 不会自动迁移或删除；迁移前请备份。

## 验证下载文件

在 ZIP 所在目录打开 PowerShell，执行：

```powershell
Get-FileHash .\KnowNexus-0.1.0-Windows-x64-portable.zip -Algorithm SHA256
```

将结果与 Release 中 `SHA256SUMS.txt` 的内容比较。两者完全一致表示下载文件完整。

## 常见问题

### 双击 EXE 没有反应

1. 确认 ZIP 已完整解压。
2. 确认 EXE 旁边仍有 `backend`、`resources`、`tesseract` 和 `models`。
3. 检查 Windows Defender 或其他安全软件是否隔离了文件。
4. 检查 KnowNexus 是否已经在系统托盘运行。
5. 查看程序目录旁 `logs` 中的日志。

### 本地检索不可用

进入“设置 → 基础配置”，确认 Embedding 和 Reranker 都显示“已就绪”。  
模型下载需要网络连接和足够的磁盘空间。  
程序会先尝试 Hugging Face 官方源，网络不可达时自动切换到备用镜像；  
如两次均失败，请检查防火墙、代理或 DNS 设置后重试。

### OCR 无法识别文字

确认使用的是完整便携包，并检查 `tesseract` 和 `tessdata` 是否存在。清晰、方向正确、对比度较高的图片通常有更好的识别效果。

### 音视频转写较慢

Whisper 在本机运行，速度取决于文件长度和电脑性能。长音视频建议先裁剪。

### 没有显示更新提示

只有 GitHub 上存在高于当前版本的正式 Release 时才会显示。草稿 Release、版本相同或网络不可用时不会提示。

## 开发

### 环境要求

- Windows 10 / 11
- Python 3.11+
- Node.js 20+
- Git

### 获取源码

```powershell
git clone https://github.com/m03000/KnowNexus.git
cd KnowNexus
```

### 安装后端

注意：仅使用源码的话不包含OCR/Whisper等组件，无法进行多模态识别，因此无法识别pdf、视频等资源。  
若需要llm识别平台链接、图片等内容则需要完整下载releases里面打包好的桌面端应用。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,learning-documents,learning-media]"
Copy-Item .env.example .env
```

编辑 `.env`，配置自己的模型服务。不要提交包含真实密钥的 `.env`。

如需限制代码解析允许访问的目录：

```dotenv
ALLOWED_PROJECT_ROOTS=["D:/Code","D:/Projects"]
```

### 安装前端并运行

```powershell
cd frontend
npm ci
cd ..
.\start_desktop.cmd
```

也可以分别运行：

```powershell
# 后端
.\.venv\Scripts\python.exe -m uvicorn study_help_agent.app.main:app --host 127.0.0.1 --port 8001

# 前端
cd frontend
npm run dev
```

### 检查和构建

```powershell
cd frontend
npm run lint
npm run build
npm run desktop:package
```

Electron 构建输出位于：

```text
frontend\release\win-unpacked\KnowNexus.exe
```

准备好完整便携目录后，可以生成 ZIP 和 SHA256：

```powershell
.\scripts\package_portable.ps1 -Version 0.1.0
```

## 项目结构

```text
KnowNexus/
├─ .github/                  GitHub Issue 模板
├─ frontend/                 React 前端、知识星图与 Electron 桌面壳
├─ integrations/             外部工具集成
├─ scripts/                  构建和维护脚本
├─ src/study_help_agent/     FastAPI 后端与核心业务
├─ var/                      本地运行数据，不提交到 Git
├─ .env.example              环境变量示例
├─ CHANGELOG.md              版本变更记录
├─ RELEASE_NOTES.md          当前版本发布说明
└─ start_desktop.cmd         源码开发启动器
```

## 参与贡献

欢迎提交 Issue 和 Pull Request。较大的功能变更建议先通过 Issue 讨论，并说明问题背景、预期行为、复现步骤、设计取舍和验证方式。

安全问题请参阅 [SECURITY.md](SECURITY.md)，贡献方式请参阅 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

KnowNexus 遵循 [MIT License](LICENSE)。第三方组件与改编代码声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
