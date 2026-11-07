---
title: 模块说明：media（识别前的媒体预处理）
owner: C
status: review
last_updated: 2026-11-07
related_code: app/pipelines/media, tests/media
summary: WAV 转为 16k 单声道 PCM16、图片方向与大小检查、号码框定位及不含原始素材的七天审计记录
audience: both
depends_on: [../tickets/T-13-媒体预处理-C.md]
---

# 模块说明：media

## 入口与边界

从 `app.pipelines.media` 导入 `prepare_audio`、`prepare_image`、`mark_sensitive_regions`；前两者返回 `MediaResult`，失败抛 `MediaPreprocessError`（`code`、中文提示、`record`）。`data` 是仅在内存中的处理结果；`metadata` 说明尺寸或时长、操作、警告和是否截断；`record` 含输入 `sha256` 和持久化处理摘要。

预处理后再将 `result.data` 传给既有的 `audio.asr.transcribe` 或 `vision.ocr.extract_text`。本票不改接口层和识别模块，当前 HTTP 上传入口尚未自动调用这一模块；没有新增识别模型或共享字段。

## 音频

- 整数 PCM WAV（8/16/24/32bit、8–192kHz、1–8 声道）混单声道、转为 16kHz PCM16，整段峰值归一且增益最多八倍；静音仍是静音。
- 最长处理前 180 秒；超长输入在 `truncated`、`operations` 和 `warnings` 中明示。输入超过 128MiB 时提示分段。
- m4a / amr / mp3 等压缩录音当前需要外部转为 16bit、16000Hz、单声道 PCM WAV；不会返回假转写或空的成功结果。预处理本身不做 VAD，已有 `transcribe` 负责切段。

## 图片与脱敏位置

- 读取 PNG / JPEG 的尺寸和 EXIF 方向；上限 4MiB、单边 4000px，超过时明确给出目标尺寸和体积，供用户缩小或裁剪。
- Windows 已有 PowerShell / System.Drawing 时，对方向 2–8 做像素翻转或旋转，输出无 EXIF 的 PNG；没有该工具或转换失败则明确拒绝并提示先纠正方向，不把歪图记成成功。
- `mark_sensitive_regions` 接受既有 OCR 文本块及图像宽高，识别手机号、已遮盖的手机号和银行卡号，保守返回整个文字块的坐标。坐标属于预处理后的图像；返回值不携带号码或文字，不声称达到单字精度，也不改写像素。
- 未配置 OCR 时只能完成图片预检查，无法凭图片字节猜出号码位置；定位须使用真实 OCR 返回的文字块。

## 留证与清理

每次音频或图片尝试（成功或拒绝）都在 `data/samples/media/audit/` 写一个摘要 JSON，也可用 `audit_dir` 指定本地目录。记录只包含 SHA-256、字节数、格式或尺寸、处理操作、固定提示、截断状态及时间；不写原始字节、文件名、OCR 文本或号码。审计写入失败会报错，不能宣称已留证。

原始和处理后的字节均由调用方在内存中持有，本模块不持久化。方向纠正使用的系统临时目录在返回或失败时清理。摘要保留七天，在下一次处理时清理过期的本模块摘要文件；长期不再调用时由部署方清理该目录。默认审计目录受现有 `.gitignore` 保护，不能使用 `git add -f` 提交媒体或本地摘要。

## 验证

`python -m pytest tests/media -q` 覆盖格式拒绝、重采样、单声道、静音、音量、时长上限、EXIF、体积提示、号码框、摘要隐私和留存。全部测试素材由代码合成，不含真实录音、截图或个人信息；真实手机素材的现场试用需另记实测，不能用合成测试冒充。
