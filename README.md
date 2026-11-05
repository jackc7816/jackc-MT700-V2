# AI 跨境贸易融资信用证单据智能审核系统 V2（教学原型）

## V2 使用流程

1. 在“信用证与单据”上传 **TXT 格式** 的 MT700 报文。
2. 核对信用证字段原文及系统根据 46A 生成的动态单据清单。
3. 按清单上传 PDF、JPG、JPEG、PNG 或 TXT 单据，核对提取字段并逐份确认。
4. 点击“执行信用证单据审核并保存历史”。结果会给出逐项规则、原文证据、交叉审核矩阵及八大风险维度。
5. 在“审核历史”查看 V2 记录与保留的旧版历史。删除必须二次确认，且仅作软删除。

V2 的审核记录保存到 SQLite 中新增的 `v2_review_runs` 和 `v2_audit_events` 表；原有 `review_runs`、`review_findings`、`audit_events` 及其历史快照不会被重算或覆盖。

### OCR 说明

本机 Windows 环境会优先读取 PDF 文字层；扫描 PDF 和图片随后尝试调用 Windows OCR。Streamlit Community Cloud 等非 Windows 环境不能使用该本地 OCR 路径，识别失败只会显示“待人工确认”，不会自动形成单据不符点。接入外部 OCR/文档服务前，必须取得机构的数据合规授权。

---

# V1 兼容说明

本升级版保留原有的手工录入、CSV 批量审核、审核按钮、下载和历史查看体验，并将单文件 JSON 历史升级为本地 SQLite 数据库。

## 已实现功能

- 20 条分层规则：LC001–LC006、BL001–BL006、DOC001–DOC004 为单据审核；RISK001–RISK004 为融资风险预警。
- 规则结果均输出编号、依据、证据、建议、严重程度、是否需人工复核，以及外部核验标记。
- 10 组教学模拟案例，保存在 `test_cases.json`；其中 CASE-009 需先登记相同发票的未结清融资余额。
- 每次点击审核创建新的 SQLite 审核记录，按时间倒序展示；页面删除是软删除，删除事件保留在 `audit_events` 表。
- 本行融资台账及 RISK001 重复融资检查。该检查不能识别其他银行的融资。
- 结构化 CSV 和 Markdown 审核报告下载。
- 已覆盖货币、金额、日期、港口、单据签署、合法“发票早于装运”例外、重复融资和外部核验状态的自动化测试。
- MT700 解析后可进入“单据提交中心”：按 46A 清单上传、分类、抽取、人工确认，再自动带入手工审单。

## 单据提交中心

1. 在“MT700 解析”上传或粘贴报文，点击“进入单据提交中心”。
2. 系统列出字段 46A 中每项单据要求；每一项都要上传并点击“确认此单据及字段”。
3. 上传后先进行分类，再抽取关键字段。用户可改正单据类型和字段值。
4. 点击“开始交叉审核”。若有未提交或尚未确认的单据，会出现弹窗逐项说明缺失内容；齐全后自动转到“手工录入”，并带入信用证基准和已确认字段。

默认在本机读取文字层。Windows 上，扫描 PDF、PNG 和 JPG 会使用系统 OCR。运行前安装 requirements.txt，并确保 Windows 安装了至少一种 OCR 语言。英文单据优先使用已安装的英文 OCR 语言，其他情况下使用系统可用语言。识别原文可在“查看识别原文”展开核对，未提取的字段可直接手填。单份扫描 PDF 最多处理 20 页。重启后请重新上传并确认单据。

如已配置获准使用的文档服务，程序仍会优先调用该服务。

```powershell
$env:DOCUMENT_CLASSIFICATION_API_URL = "https://your-approved-service/classify"
$env:DOCUMENT_EXTRACTION_API_URL = "https://your-approved-service/extract"
```

接口接收 JSON，包含 `filename`、`content_base64`；分类接口应返回 `document_type`（可选 `confidence`），抽取接口应返回 `fields` 对象。请仅连接获得数据合规授权的服务。

## 运行

在项目目录运行：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

浏览器打开终端显示的本地地址（通常为 `http://localhost:8501`）。如 PowerShell 不允许激活环境，先在当前终端执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 测试

```powershell
python -m unittest discover -s tests -v
```

本次交付的测试结果：11 项通过。测试包括模拟案例、重复融资、合法日期例外、MT700 条款解析、46A 单据拆分、本地分类/抽取回退及未配置 OCR 时不误报为已提取。

## 使用边界

UCP 600/ISBP 821 的引用仅用于教学规则映射；具体单据结论仍取决于完整信用证、适用条款及有权限的人工审核。系统**不**联网核验承运人、制裁名单、受益所有人或市场价格。相关字段显示“未核验/资料不足”不是失败结论，也不能被当作已完成核验。

不要将真实客户数据放入此本地教学原型。它没有生产级访问控制、加密、备份、并发控制或外部合规数据授权。
