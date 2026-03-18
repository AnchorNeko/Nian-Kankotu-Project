# Nian Kantoku

从剧情大纲生成动漫分镜与视频片段，并将结果写入指定输出目录。

## 项目做什么
Nian Kantoku 面向开发者提供一个可脚本化的命令行流程：
- 输入剧情大纲文本（可选参考图）。
- 生成分镜、关键帧、镜头视频片段与运行清单。
- 在镜头成功时输出合并后的视频文件。

## 环境要求
- Python `>=3.9`
- `ffmpeg`
- Ark API Key（环境变量 `ARK_API_KEY`）

## 快速开始
1. 安装依赖：
```bash
pip install -e .
```

2. 设置 API Key：
```bash
export ARK_API_KEY=your-ark-api-key
```

3. 执行生成：
```bash
nian-kantoku run \
  --outline-file /path/to/outline.txt \
  --output-dir /path/to/outputs/run_001 \
  --config config/settings.yaml
```

## 输入与输出
- 输入参数
  - `--outline-file`：必填，大纲文件（`.txt` 或 `.md`）
  - `--output-dir`：必填，输出目录
  - `--reference-dir`：可选，参考图目录（支持 `character_*`、`style_*`、`scene_*` 命名）
  - `--config`：可选，配置文件路径（默认 `config/settings.yaml`）
- 关键输出（位于 `--output-dir`）
  - `storyboard.json`
  - `keyframes/`
  - `clips/`
  - `run_manifest.json`
  - `shot_diagnostics.jsonl`
  - `final.mp4`（全部镜头成功时生成）

## 常用开发命令
```bash
pytest -q
python scripts/verify_arch_sync.py
```

## 架构说明
项目采用分层架构，详情见 [docs/architecture.md](docs/architecture.md)。

## 安全提示
- 不要提交 `.env`、`.env.*`、`outputs/` 等本地运行数据。
- 密钥仅通过环境变量注入，不要写入代码或配置文件。
