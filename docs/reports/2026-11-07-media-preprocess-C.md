---
title: 任务回执：T-13 媒体预处理（负责人 C）
owner: C
status: review
last_updated: 2026-11-07
related_code: app/pipelines/media, tests/media
summary: WAV 转 16k 单声道、明确截断与转码提示、EXIF 像素纠正、号码框及七天无原始素材摘要；合成素材验收通过，待真实手机现场试用
audience: agent
depends_on: [../tickets/T-13-媒体预处理-C.md, ../modules/media.md, ../进度.md]
---

# 任务回执：T-13 媒体预处理

## 做了什么

- 音频：整数 PCM WAV 转 16k 单声道 PCM16、峰值归一（增益最多八倍）、最长处理前 180 秒并明确警告；m4a / amr 等压缩录音给出明确 PCM WAV 转码指引。
- 图片：PNG/JPEG 结构检查；Windows 现有 PowerShell / System.Drawing 纠正 EXIF 2–8（含镜像），去 EXIF 后输出 PNG；无工具明确拒绝。超 4MiB 或单边 4000px 提示目标尺寸和体积。
- 脱敏与留证：基于真实 OCR 文本块标注手机号/卡号所在整块，返回值不含文字；音频与图片每次成功或拒绝都保存 SHA-256、操作、警告及截断状态。原图旋转时仅短暂使用自动清理的系统临时文件，不入库、不长期留存；摘要七天后在下次调用清理。
- 56 项新测试及既有 144 项测试通过。独立只读音频复核和图片像素复核均未发现阻断；未改路由、识别实现、共享契约、门禁或依赖。
- 契约变更：无。进度已更新：是（当前状态、已完成、进行中、已知问题、下一步）。

## 没做完 / 已知问题

- 未提供六组真实手机素材：以下是合成素材/异常输入的验证，不能宣称已用真实微信、iPhone、手机号截图实测；未向群发送消息。
- 本票禁止改接口层：既有 HTTP 上传入口尚未接入预处理。压缩录音未内置转码器，需先转 PCM WAV；Linux 没有本模块所用的 Windows 工具时，需要先在相册中纠正方向。超大图提供裁剪/导出建议，不自动缩放。
- 手机号/卡号定位依赖既有 OCR 文本块，只匹配单个文字块中的候选号码，尚未跨块合并，也未真正打码。JPEG 校验是结构检查，不保证熵编码的完整可解码性；PNG 另有 CRC、有界解压和行过滤校验。
- 测试仅有一条既有依赖弃用警告（FastAPI / Starlette 的 TestClient）；未为此增加依赖。
- GitHub 发布结果见文末；先前缺少凭据的阻塞已通过浏览器授权解决。

## 下次接手要知道什么

- 入口、参数和保留策略见 [media 模块说明](../modules/media.md)。调用 `prepare_audio` / `prepare_image` 后，将 `result.data` 传给原有识别函数；号码框的坐标以处理后的图片为准。
- 默认摘要：`data/samples/media/audit/`，已由现有 `.gitignore` 忽略；也可通过 `audit_dir` 指定本地目录。摘要不含文件名、OCR 文本、号码或原始字节。审计写入失败会明确报错；长期不再调用时由部署方清理过期摘要。
- 代码提交：`432d1bb feat(media): add auditable audio and image preprocessing`。没有强推或向 main 推送；当前分支 `feature/media-preprocess`。

| 任务单场景 | 本次实际验证及结果 | 尚待验证 |
| --- | --- | --- |
| 微信 m4a（及 amr） | m4a 压缩格式输入明确拒绝并指导转为 16bit/16000Hz/单声道 PCM WAV，失败留摘要 | 真实微信导出的录音与转码后质量 |
| iPhone 3 秒录音 | 合成三秒 PCM 波形经预处理，再调用原有 transcribe 得到一个有声区间和正确时长 | iPhone 原生 m4a 不能直接解码；待导出或转码后的录音实测 |
| 48k 立体声 | 输出 16k/mono/PCM16；三秒时长不漂移；30 秒合成录音性能测试 <10s（独立复核约 0.48s） | 真实录音的听感与模型转写 |
| 竖拍截图 | 合成非对称彩色 PNG / EXIF 2–8 的实际输出像素逐一核对，方向与宽高正确，无 EXIF | 真实手机 JPEG/PNG 现场复测 |
| 5MiB 长截图 | 1000×5000px 合成 PNG 给出 800×4000px、4194304 字节以内的明确提示 | 用户裁剪或压缩后真实 OCR 可读性 |
| 手机号/卡号截图 | 合成 OCR Block 使用脱敏手机号和虚构卡号，整块框裁到图内，返回值不含号码文本 | 真实截图经 OCR 后的框及跨块情况 |

## 怎么验收

运行环境：Windows / Python 3.14.6；依赖仅安装仓库现有 `requirements.txt`。冒烟使用本地 8123 端口，服务加载 15 剧本、50 案例。Linux CI 中，七个依赖 Windows 实际像素工具的用例按平台跳过，缺工具的明确拒绝仍有测试覆盖。

```text
命令：pwsh scripts/check.ps1 -Task lint -Python D:\Python\python.exe
输出：
All checks passed!

==================== 汇总 ====================
[PASS] lint
结果：全绿。把这段输出整段贴进 PR 描述。
```

```text
命令：pwsh scripts/check.ps1 -Task test -Python D:\Python\python.exe
输出：
........................................................................ [ 36%]
........................................................................ [ 72%]
........................................................                 [100%]
============================== warnings summary ===============================
..\..\Python\Lib\site-packages\fastapi\testclient.py:1
  D:\Python\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
200 passed, 1 warning in 5.75s

==================== 汇总 ====================
[PASS] test
结果：全绿。把这段输出整段贴进 PR 描述。
```

```text
命令：pwsh scripts/check.ps1 -Task smoke -Python D:\Python\python.exe -BaseUrl http://127.0.0.1:8123
输出：
[PASS] 1/5 health :: status=200 kb_scripts=15
[PASS] 2/5 诈骗文本判为高危 :: status=200 score=87.3 level=3
[PASS] 3/5 正常文本不误报 :: status=200 score=7.5 level=0
[PASS] 4/5 端到端 < 10s :: latency=24ms
[PASS] 5/5 空文本被拒 :: status=422

结果：5/5 全部通过

==================== 汇总 ====================
[PASS] smoke
结果：全绿。把这段输出整段贴进 PR 描述。
```

```text
命令：python scripts/docs.py check
输出：
! docs/需求覆盖表.md:1  还有 2 条需求没有主责任务：FR-4.2、FR-4.3
OK    阻断 0 / 警告 1 项
```

## 改动清单

- `app/pipelines/media/`：音频、图片、统一错误和仅含摘要的留痕。
- `tests/media/`：56 项正反例、方向像素、拒绝留痕、临时清理、保留期限和性能验证。
- `docs/modules/media.md`、本回执、T-13 完成记录和进度页；INDEX 与需求覆盖表使用原脚本生成。

## GitHub 发布状态

分支 `feature/media-preprocess` 已推送；[PR #18](https://github.com/yu-nianan/tol/pull/18) 已创建，目标 `main`，未合并，未直接推 main。PR 正文含四条命令完整输出、契约与进度声明。

首次非交互推送因没有登录凭据失败（退出码 128）；随后浏览器授权完成，推送成功。原始错误：

```text
fatal: Cannot prompt because user interactivity has been disabled.
fatal: could not read Username for 'https://github.com': terminal prompts disabled
```
