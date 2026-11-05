"""Streamlit user interface for the V2 credit-document review workflow."""
from __future__ import annotations

import hashlib
import json
import os

import pandas as pd
import streamlit as st

from core import list_reviews, review_detail, soft_delete_review
from document_processing import DOCUMENT_TYPES, classify_document, extract_document, extract_document_with_structure
from mt700 import parse_mt700
from v2_ingestion import read_document_evidence
from v2_review import DISCREPANCY, NEED_INFO, build_review
from v2_storage import init_v2_db, list_v2_reviews, save_v2_review, soft_delete_v2_review, v2_review_detail

FIELD_LABELS = {
    "Filename": "Filename", "Document Type": "Document Type", "Extraction Status": "Extraction Status",
    "OCR Text Preview": "OCR Text Preview", "文件名": "Filename", "文档类型": "Document Type",
    "提取状态": "Extraction Status", "可读文本预览": "OCR Text Preview",
    "bill_of_lading_number": "Bill of Lading Number", "booking_number": "Booking Number",
    "shipper": "Shipper", "consignee": "Consignee", "notify_party": "Notify Party",
    "place_of_receipt": "Place of Receipt", "port_of_loading": "Port of Loading",
    "port_of_discharge": "Port of Discharge", "place_of_delivery": "Place of Delivery",
    "ocean_vessel_voyage": "Vessel / Voyage", "vessel_name": "Vessel Name",
    "voyage_number": "Voyage Number", "shipping_line": "Shipping Line", "date_laden_on_board": "On-board Date",
    "issue_date": "Issue Date", "freight_payment_term": "Freight Payment Term", "original_count": "Original Count",
    "carrier": "Carrier", "exporter": "Exporter", "order_number": "Order Number",
    "packing_list_number": "Packing List Number", "container_count": "Container Count",
    "total_package_count": "Total Package Count", "total_package_type": "Package Type",
    "total_bundle_count": "Total Bundle Count", "total_piece_count": "Total Piece Count",
    "gross_weight": "Total Gross Weight", "net_weight": "Total Net Weight",
    "total_gross_weight": "Total Gross Weight", "total_net_weight": "Total Net Weight",
    "container_gross_weight_total": "Container Gross Weight Total", "goods_description": "Goods Description",
    "marks_and_numbers": "Marks and Numbers", "table_validation": "Container Detail Validation",
    "装箱单号": "Packing List Number", "装箱单货物描述": "Goods Description",
    "装箱单数量": "Total Bundle Count", "装箱单装货港": "Port of Loading",
    "装箱单卸货港": "Port of Discharge", "装箱单毛重": "Total Gross Weight",
    "装箱单净重": "Total Net Weight", "提单号": "Bill of Lading Number",
    "原产地证号": "Certificate Number", "原产地证货物描述": "Goods Description",
    "原产地证数量": "Quantity", "原产国": "Country of Origin",
    "保险单号": "Insurance Certificate Number", "保险币种": "Insurance Currency", "保险金额": "Insured Value",
    "保险货物描述": "Goods Description", "保险数量": "Insured Quantity", "保险索赔代理": "Claims Agent",
    "装运日": "On-board Date", "提单装货港": "Port of Loading",
    "提单卸货港": "Port of Discharge", "提单货物描述": "Goods Description",
    "提单数量": "Quantity",
}

# Interface labels are Chinese; documentary values are always retained verbatim.
FIELD_LABELS.update({
    "bill_of_lading_number": "提单号码", "booking_number": "订舱号码", "shipper": "发货人", "consignee": "收货人", "notify_party": "通知方",
    "place_of_receipt": "收货地", "port_of_loading": "装货港", "port_of_discharge": "卸货港", "place_of_delivery": "交货地",
    "ocean_vessel_voyage": "船名／航次", "date_laden_on_board": "装船日期", "issue_date": "签发日期", "freight_payment_term": "运费支付方式",
    "original_count": "正本份数", "carrier": "承运人", "container_count": "集装箱数量", "total_package_count": "总包装数量",
    "total_package_type": "包装单位", "total_piece_count": "总件数", "gross_weight": "总毛重", "net_weight": "总净重",
    "container_gross_weight_total": "集装箱毛重合计", "goods_description": "货物描述", "table_validation": "集装箱明细核验",
    "提单号": "提单号码", "装运日": "装船日期", "提单装货港": "装货港", "提单卸货港": "卸货港", "提单货物描述": "货物描述", "提单数量": "提单数量",
    "保险单号": "保险证书号", "保险币种": "保险币种", "保险金额": "保险金额", "保险货物描述": "保险货物描述", "保险数量": "保险数量", "保险索赔代理": "越南索赔代理",
})


def _field_label(name: str) -> str:
    """Translate UI labels only; OCR values must remain verbatim evidence."""
    return FIELD_LABELS.get(name, name)


def _init_state() -> None:
    defaults = {
        "v2_lc": None,
        "v2_requirements": [],
        "v2_documents": {},
        "v2_review": None,
        "v2_saved_signature": "",
        "v2_delete_target": None,
        "v2_batch_messages": [],
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _reset_case(parsed: dict) -> None:
    requirements = [dict(item, requirement_id=f"REQ-{index:02d}") for index, item in enumerate(parsed["document_requirements"], start=1)]
    st.session_state["v2_lc"] = parsed["record"]
    st.session_state["v2_requirements"] = requirements
    st.session_state["v2_documents"] = {}
    st.session_state["v2_review"] = None
    st.session_state["v2_saved_signature"] = ""


def _document_signature(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _document_rows() -> list[dict]:
    rows = []
    for requirement in st.session_state["v2_requirements"]:
        document = st.session_state["v2_documents"].get(requirement["requirement_id"])
        rows.append(
            {
                "编号": requirement["requirement_id"],
                "信用证要求": requirement["单据类型"],
                "正本": requirement.get("正本") or "待人工确认",
                "副本": requirement.get("副本") or "待人工确认",
                "状态": "已确认" if document and document.get("confirmed") else ("待确认" if document else "未上传"),
            }
        )
    return rows


def _set_document(requirement: dict, uploaded) -> dict:
    content = uploaded.getvalue()
    evidence_result = read_document_evidence(uploaded.name, content)
    classification = classify_document(uploaded.name, content, evidence_result["text"])
    extraction, structured = extract_document_with_structure(
        uploaded.name, content, classification["document_type"],
        evidence_result["text"], evidence_result["evidence"], evidence_result["status"],
    )
    document = {
        "requirement_id": requirement["requirement_id"],
        "filename": uploaded.name,
        "signature": _document_signature(content),
        "document_type": classification["document_type"],
        "classification": classification,
        "fields": extraction,
        "text": evidence_result["text"],
        "evidence": evidence_result["evidence"],
        "read_status": evidence_result["status"],
        "read_sources": [evidence_result["status"]],
        "structured": structured,
        "confirmed": False,
    }
    st.session_state["v2_documents"][requirement["requirement_id"]] = document
    return document


def _add_batch_documents(uploaded_files) -> None:
    """Classify uploads; consecutive pages of one document are merged safely."""
    messages = []
    requirements = st.session_state["v2_requirements"]
    documents = st.session_state["v2_documents"]
    for uploaded in uploaded_files:
        content = uploaded.getvalue()
        signature = _document_signature(content)
        if any(signature in item.get("page_signatures", [item.get("signature")]) for item in documents.values()):
            messages.append(f"{uploaded.name}：已存在，未重复加入。")
            continue
        with st.spinner(f"正在识别 {uploaded.name}…"):
            evidence = read_document_evidence(uploaded.name, content)
            classification = classify_document(uploaded.name, content, evidence["text"])
        candidates = [
            requirement for requirement in requirements
            if requirement["单据类型"] == classification["document_type"] and requirement["requirement_id"] not in documents
        ]
        existing_candidates = [
            requirement for requirement in requirements
            if requirement["单据类型"] == classification["document_type"]
            and documents.get(requirement["requirement_id"], {}).get("document_type") == classification["document_type"]
        ]
        if not candidates and not existing_candidates:
            messages.append(f"{uploaded.name}：识别为“{classification['document_type']}”，但未能自动匹配到尚未提交的信用证要求；请在对应单据卡片中单独上传。")
            continue
        requirement = candidates[0] if candidates else existing_candidates[0]
        previous = documents.get(requirement["requirement_id"])
        if previous:
            page_offset = max((int(item.get("page", 1)) for item in previous.get("evidence", [])), default=0)
            appended_evidence = [dict(item, page=int(item.get("page", 1)) + page_offset) for item in evidence["evidence"]]
            combined_text = "\n".join(part for part in (previous.get("text", ""), evidence["text"]) if part)
            combined_evidence = previous.get("evidence", []) + appended_evidence
            read_sources = previous.get("read_sources", [previous.get("read_status", "")]) + [evidence["status"]]
            extraction, structured = extract_document_with_structure(
                previous["filename"] + "；" + uploaded.name, b"", classification["document_type"],
                combined_text, combined_evidence, "多页 OCR/文字证据",
            )
            previous.update({
                "filename": previous["filename"] + "；" + uploaded.name,
                "signature": hashlib.sha256((previous["signature"] + signature).encode()).hexdigest(),
                "page_signatures": previous.get("page_signatures", [previous["signature"]]) + [signature],
                "fields": extraction, "structured": structured, "text": combined_text,
                "evidence": combined_evidence,
                "read_sources": read_sources,
                "read_status": "已合并多页单据；" + "；".join(dict.fromkeys(source for source in read_sources if source)),
                "confirmed": False,
            })
            messages.append(f"{uploaded.name}：已追加到 {requirement['requirement_id']} 的同一份多页{classification['document_type']}。")
            continue
        extraction, structured = extract_document_with_structure(uploaded.name, content, classification["document_type"], evidence["text"], evidence["evidence"], evidence["status"])
        documents[requirement["requirement_id"]] = {
            "requirement_id": requirement["requirement_id"],
            "filename": uploaded.name,
            "signature": signature,
            "page_signatures": [signature],
            "document_type": classification["document_type"],
            "classification": classification,
            "fields": extraction,
            "text": evidence["text"],
            "evidence": evidence["evidence"],
            "read_status": evidence["status"], "read_sources": [evidence["status"]],
            "structured": structured,
            "confirmed": False,
        }
        messages.append(f"{uploaded.name}：已归入 {requirement['requirement_id']}｜{requirement['单据类型']}，请核对字段后确认。")
    st.session_state["v2_batch_messages"] = messages


def _render_lc_upload() -> None:
    st.header("1. 上传并解析 MT700")
    st.caption("V2 仅接受 MT700 TXT 文件。系统保留字段原文；解析结果须由审核员核对。")
    uploaded = st.file_uploader("选择 MT700 TXT 文件", type=["txt"], key="v2_mt700_upload")
    if not uploaded:
        return
    message = uploaded.getvalue().decode("utf-8", errors="replace")
    parsed = parse_mt700(message)
    for warning in parsed["warnings"]:
        st.warning(warning)
    if st.button("确认信用证解析并生成单据清单", type="primary", key="v2_confirm_mt700", icon=":material/fact_check:"):
        _reset_case(parsed)
        st.success("已生成单据清单。请继续上传单据并确认字段。")
        st.rerun()

    st.subheader("解析预览")
    st.dataframe(pd.DataFrame(parsed["fields"]), hide_index=True, alt="MT700 解析字段和原文")
    for field in ("45A", "46A", "47A", "78", "72Z"):
        row = next((item for item in parsed["fields"] if item["SWIFT 字段"] == field), None)
        if row:
            with st.expander(f"{field}｜{row['含义']}"):
                st.text(row["原文内容"])


def _render_documents() -> None:
    lc = st.session_state["v2_lc"]
    requirements = st.session_state["v2_requirements"]
    if not lc:
        _render_lc_upload()
        return

    st.header("2. 信用证摘要与单据清单")
    st.dataframe(
        pd.DataFrame([
            {"字段": label, "值": lc.get(key) or "未识别"}
            for label, key in [("信用证编号", "信用证编号"), ("币种", "信用证币种"), ("金额", "信用证金额"), ("受益人", "受益人"), ("申请人", "信用证申请人"), ("最迟装运日", "最迟装运日")]
        ]),
        hide_index=True,
        alt="信用证摘要",
    )
    if not requirements:
        st.warning("未能从字段 46A 识别单据要求。请更换完整 MT700 TXT，或在下一阶段增加人工补录单据要求。")
        return
    st.dataframe(pd.DataFrame(_document_rows()), hide_index=True, alt="动态单据清单")

    st.header("3. 上传贸易单据并确认字段")
    st.caption("支持 PDF、JPG、JPEG、PNG、TXT。PDF 优先读取文字层；扫描件/图片尝试本地 OCR。识别失败只会标记待确认。")
    batch = st.file_uploader(
        "批量上传贸易单据（一次可选择多个不同文件）",
        type=["pdf", "jpg", "jpeg", "png", "txt"],
        accept_multiple_files=True,
        key="v2_batch_upload",
        help="可一次选择发票、提单、装箱单等多个文件；系统会根据文件名及 OCR/文字内容归入对应的信用证要求。",
    )
    if batch and st.button("识别并加入这批文件", key="v2_add_batch", icon=":material/playlist_add:"):
        _add_batch_documents(batch)
        st.rerun()
    for message in st.session_state.get("v2_batch_messages", []):
        st.info(message)
    for requirement in requirements:
        requirement_id = requirement["requirement_id"]
        saved = st.session_state["v2_documents"].get(requirement_id)
        with st.container(border=True):
            st.subheader(f"{requirement_id}｜{requirement['单据类型']}")
            st.caption(requirement.get("原始条款", ""))
            uploaded = st.file_uploader(
                "上传或替换此项单据（此处也可多选）",
                type=["pdf", "jpg", "jpeg", "png", "txt"],
                accept_multiple_files=True,
                key=f"v2_upload_{requirement_id}",
            )
            if uploaded and st.button("识别并加入所选文件", key=f"v2_add_{requirement_id}", icon=":material/playlist_add:"):
                _add_batch_documents(uploaded)
                st.rerun()
            if not saved:
                continue
            st.caption(f"读取状态：{saved['read_status']}｜分类：{saved['classification']['source']}｜{saved['classification']['confidence']}")
            doc_type = st.selectbox("确认单据类型", DOCUMENT_TYPES, index=DOCUMENT_TYPES.index(saved["document_type"]), key=f"v2_type_{requirement_id}")
            if doc_type != saved["document_type"]:
                saved["document_type"] = doc_type
                # The current uploader may be empty on a later rerun; use saved OCR evidence.
                saved["fields"], saved["structured"] = extract_document_with_structure(
                    saved["filename"], b"", doc_type,
                    saved["text"], saved["evidence"], saved["read_status"],
                )
                saved["confirmed"] = False
                st.session_state["v2_documents"][requirement_id] = saved
            if st.button("按当前规则重新提取（不调用 OCR）", key=f"v2_reextract_{requirement_id}", icon=":material/refresh:"):
                saved["fields"], saved["structured"] = extract_document_with_structure(
                    saved["filename"], b"", saved["document_type"],
                    saved["text"], saved["evidence"], saved["read_status"],
                )
                saved["confirmed"] = False
                st.session_state["v2_documents"][requirement_id] = saved
                st.rerun()
            editable = {
                key: value for key, value in saved["fields"].items()
                if key not in {"文件名", "文档类型", "提取状态", "可读文本预览"}
            }
            # Show every structured field as well.  Its English identifier is stable
            # for cross-review; the original OCR evidence remains in ``structured``.
            for field_name, detail in saved.get("structured", {}).get("fields", {}).items():
                editable.setdefault(field_name, detail.get("value", "") if isinstance(detail, dict) else "")
            edited = st.data_editor(
                pd.DataFrame(
                    [{"内部字段": key, "字段": _field_label(key), "提取值": value} for key, value in editable.items()]
                ),
                hide_index=True,
                disabled=["内部字段", "字段"],
                column_config={"内部字段": None},
                key=f"v2_fields_{requirement_id}",
                alt=f"{requirement['单据类型']}提取字段",
            )
            if saved.get("text"):
                with st.expander("查看原文与可用定位信息"):
                    st.text(saved["text"][:12000])
                    if saved["evidence"]:
                        st.dataframe(pd.DataFrame(saved["evidence"][:200]), hide_index=True, alt="单据文字证据定位")
            structured = saved.get("structured", {})
            if structured.get("table_data"):
                with st.expander("查看识别出的表格明细（需人工确认）"):
                    st.dataframe(pd.DataFrame(structured["table_data"]), hide_index=True, alt="单据表格明细")
                    validation = structured.get("fields", {}).get("table_validation", {})
                    for issue in validation.get("issues", []) if isinstance(validation, dict) else []:
                        st.warning(f"表格汇总待复核：{issue['kind']}（单据 {issue['declared']}，明细计算 {issue['calculated']}）。")
            if st.button("确认该单据与字段", key=f"v2_confirm_{requirement_id}", icon=":material/task_alt:"):
                changes = dict(zip(edited["内部字段"], edited["提取值"].fillna("")))
                saved["fields"].update(changes)
                for field_name, detail in saved.get("structured", {}).get("fields", {}).items():
                    if field_name in changes and isinstance(detail, dict):
                        detail["value"] = str(changes[field_name])
                        detail["confirmed"] = True
                        detail["method"] = "manual_confirmation"
                saved["confirmed"] = True
                st.session_state["v2_documents"][requirement_id] = saved
                st.success("已确认。")

    _render_review_action()


def _render_review_action() -> None:
    st.header("4. 执行审核")
    documents = list(st.session_state["v2_documents"].values())
    unconfirmed = [row["编号"] for row in _document_rows() if row["状态"] != "已确认"]
    if unconfirmed:
        st.warning("以下信用证要求单据尚未确认：" + "、".join(unconfirmed))
    if st.button("执行信用证单据审核并保存历史", type="primary", key="v2_run_review", icon=":material/play_arrow:"):
        review = build_review(st.session_state["v2_lc"], st.session_state["v2_requirements"], documents)
        signature = hashlib.sha256(json.dumps(review, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        if signature == st.session_state["v2_saved_signature"]:
            st.info("当前案件内容未变化，已避免重复保存相同审核记录。")
        else:
            run_id = save_v2_review(review)
            st.session_state["v2_saved_signature"] = signature
            st.session_state["v2_review"] = review
            st.success(f"审核已保存，记录号：{run_id}")
    if st.session_state.get("v2_review"):
        _render_review(st.session_state["v2_review"])


def _render_review(review: dict) -> None:
    summary = review["summary"]
    st.header("5. 结构化审核报告")
    color = {"RED": "red", "YELLOW": "orange", "GREEN": "green"}[summary["risk_level"]]
    st.markdown(f"## :{color}[{summary['risk_level']}｜{summary['conclusion']}]")
    st.dataframe(pd.DataFrame([{"风险维度": key, "等级": value} for key, value in review["risk_dimensions"].items()]), hide_index=True, alt="八大风险维度结果")
    st.subheader("交叉审核矩阵")
    st.dataframe(pd.DataFrame([{key: value for key, value in row.items() if key != "证据"} for row in review["matrix"]]), hide_index=True, alt="跨单据交叉审核矩阵")
    st.subheader("逐项审核结果")
    rows = [{key: value for key, value in finding.items() if key not in {"evidence", "human_review_required"}} for finding in review["findings"]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, alt="逐项审核结果")
    for finding in review["findings"]:
        if finding["status"] in {DISCREPANCY, NEED_INFO}:
            with st.expander(f"{finding['rule_id']}｜{finding['rule_name']}｜{finding['status']}"):
                st.write(f"依据：{finding['basis']}")
                st.write(f"说明：{finding['explanation']}")
                if finding["evidence"]:
                    st.dataframe(pd.DataFrame(finding["evidence"]), hide_index=True, alt="审核证据")


@st.dialog("确认删除审核记录")
def _delete_dialog(kind: str, run_id: str, label: str) -> None:
    st.warning(f"将软删除“{label}”。记录不再在普通历史中显示，但审计痕迹会保留。")
    with st.container(horizontal=True):
        if st.button("确认删除", type="primary", key=f"v2_delete_yes_{run_id}"):
            if kind == "v2":
                soft_delete_v2_review(run_id)
            else:
                soft_delete_review(run_id)
            st.session_state["v2_delete_target"] = None
            st.rerun()
        if st.button("取消", key=f"v2_delete_no_{run_id}"):
            st.session_state["v2_delete_target"] = None
            st.rerun()


def _render_history() -> None:
    st.header("审核历史")
    st.caption("V2 与旧版历史同时展示；删除为软删除，需二次确认。")
    rows = []
    for item in list_v2_reviews():
        rows.append({"kind": "v2", "id": item["id"], "time": item["created_at"], "label": item["lc_number"] or "未识别信用证号", "conclusion": item["conclusion"], "version": item["rule_version"]})
    for item in list_reviews():
        rows.append({"kind": "v1", "id": item["id"], "time": item["created_at"], "label": item["transaction_id"] or "未命名交易", "conclusion": item["conclusion"], "version": item["rule_version"]})
    rows.sort(key=lambda item: item["time"], reverse=True)
    if not rows:
        st.info("尚无审核记录。")
        return
    for item in rows:
        with st.expander(f"{item['time'][:19]}｜{item['label']}｜{item['conclusion']}｜{item['version']}"):
            if item["kind"] == "v2":
                review = v2_review_detail(item["id"])
                if review:
                    _render_review(review)
            else:
                run, findings = review_detail(item["id"])
                st.info("这是旧版历史快照，保留原结果，不按 V2 规则重算。")
                payload = json.loads(run["payload"])
                st.dataframe(pd.DataFrame(findings), hide_index=True, alt="旧版审核发现")
                with st.expander("查看旧版原始输入"):
                    st.json(payload)
            if st.button("删除此记录", key=f"v2_history_delete_{item['kind']}_{item['id']}", icon=":material/delete:"):
                _delete_dialog(item["kind"], item["id"], item["label"])


def run() -> None:
    for environment_name in ("TENCENT_SECRET_ID", "TENCENT_SECRET_KEY", "TENCENT_OCR_REGION"):
        value = st.secrets.get(environment_name, "")
        if value:
            os.environ[environment_name] = str(value)
    init_v2_db()
    _init_state()
    st.title("AI 跨境贸易融资信用证单据智能审核系统 V2")
    st.caption("教学原型：结果必须由具备权限的审单人员结合完整信用证、修改书及原件确认。")
    section = st.segmented_control("工作区", ["信用证与单据", "审核报告", "审核历史"], default="信用证与单据", key="v2_section", width="stretch")
    if section == "信用证与单据":
        _render_documents()
    elif section == "审核报告":
        if st.session_state.get("v2_review"):
            _render_review(st.session_state["v2_review"])
        else:
            st.info("请先完成信用证解析、单据确认并执行审核。")
    else:
        _render_history()


if __name__ == "__main__":
    run()
