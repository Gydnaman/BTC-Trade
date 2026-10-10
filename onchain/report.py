"""Render a safe, deterministic report from an audited pool summary."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import html

from onchain.manifest import validate_manifest


def _text(value: str) -> str:
    flattened = " ".join(value.split())
    escaped = html.escape(flattened, quote=False)
    for token in ("\\", "`", "*", "_", "[", "]", "(", ")", "|", "#"):
        escaped = escaped.replace(token, "\\" + token)
    return escaped


def _amount(value: object, field: str) -> str:
    if isinstance(value, bool):
        raise ValueError(f"summary.{field} must be a finite decimal")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"summary.{field} must be a finite decimal") from exc
    if not amount.is_finite():
        raise ValueError(f"summary.{field} must be a finite decimal")
    return format(amount, "f")


def _count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"summary.{field} must be a non-negative integer")
    return value


def render_pool_report(summary: dict, manifest: dict) -> str:
    """Render only complete summaries and label synthetic versus RPC evidence."""
    manifest = validate_manifest(manifest)
    if not isinstance(summary, dict) or summary.get("status") not in {"ok", "reorg_detected"}:
        raise ValueError("report requires a complete audited summary")
    if summary.get("identity_status") != manifest["identity_status"]:
        raise ValueError("summary identity does not match manifest")
    source = summary.get("source_status")
    if source not in {"synthetic_fixture", "rpc_verified"}:
        raise ValueError("summary source_status is invalid")
    if source == "rpc_verified" and manifest["identity_status"] != "node_verified":
        raise ValueError("RPC report requires a node-verified manifest")
    block_range = summary.get("block_range")
    if (not isinstance(block_range, list) or len(block_range) != 2 or
            any(isinstance(value, bool) or not isinstance(value, int) or value < 1
                for value in block_range) or block_range[1] < block_range[0]):
        raise ValueError("summary.block_range is invalid")
    swap_count = _count(summary.get("swap_count"), "swap_count")
    duplicate_count = _count(summary.get("duplicate_count"), "duplicate_count")
    reorged_count = _count(summary.get("reorged_rows_count"), "reorged_rows_count")
    prices = summary.get("price_observations")
    liquidity = summary.get("liquidity_observations")
    limitations = summary.get("limitations")
    if (not isinstance(prices, list) or not isinstance(liquidity, list) or
            not isinstance(limitations, list) or
            any(not isinstance(item, str) for item in limitations)):
        raise ValueError("summary observations or limitations are invalid")
    if len(prices) != swap_count or len(liquidity) != swap_count:
        raise ValueError("summary event and observation counts do not match")

    if source == "synthetic_fixture":
        title = "# 合成工程夹具：Uniswap V3 事件处理演示"
        source_line = "数据来源：合成工程测试夹具；不是链上证据。"
    else:
        title = "# Uniswap V3 池事件分析"
        source_line = "数据来源：经节点核验的 RPC 事件与 canonical block 哈希。"
    lines = [
        title,
        "",
        source_line,
        f"身份核验：{manifest['identity_status']}",
        f"Chain ID：{manifest['chain_id']}",
        f"Pool：`{manifest['pool_address']}`",
        f"Token0 / Token1：`{manifest['token_addresses'][0]}` / `{manifest['token_addresses'][1]}`",
        f"Decimals：{manifest['decimals'][0]} / {manifest['decimals'][1]}",
        f"Fee tier（百万分率）：{manifest['fee_tier']}",
        f"区块区间：{block_range[0]}–{block_range[1]}（含首尾）",
        f"审计状态：{summary['status']}",
        f"交换事件数：{swap_count}",
        f"去重事件数：{duplicate_count}",
        f"已剔除重组事件：{reorged_count}",
        "",
        "## 资金流摘要",
        "",
        f"- Token0 毛流量：{_amount(summary.get('gross_token0_volume'), 'gross_token0_volume')}",
        f"- Token1 毛流量：{_amount(summary.get('gross_token1_volume'), 'gross_token1_volume')}",
        f"- Token0 净池余额变化：{_amount(summary.get('net_token0_delta'), 'net_token0_delta')}",
        f"- Token1 净池余额变化：{_amount(summary.get('net_token1_delta'), 'net_token1_delta')}",
        "",
        "## Swap 后价格观察（Token1 / Token0）",
        "",
        "| 区块 | 价格 | Tick |",
        "|---:|---:|---:|",
    ]
    for item in prices:
        if not isinstance(item, dict):
            raise ValueError("price observation must be an object")
        block = _count(item.get("block_number"), "price block")
        tick = item.get("tick")
        if isinstance(tick, bool) or not isinstance(tick, int):
            raise ValueError("price observation tick must be an integer")
        lines.append(
            f"| {block} | {_amount(item.get('token1_per_token0'), 'price')} | {tick} |"
        )
    lines.extend(["", "## 流动性观察", "", "| 区块 | 原始 liquidity |", "|---:|---:|"])
    for item in liquidity:
        if not isinstance(item, dict):
            raise ValueError("liquidity observation must be an object")
        lines.append(
            f"| {_count(item.get('block_number'), 'liquidity block')} | "
            f"{_count(item.get('liquidity_raw'), 'liquidity_raw')} |"
        )
    lines.extend(["", "## 解读限制", ""])
    lines.extend(f"- {_text(item)}" for item in limitations)
    lines.extend([
        "- 事件数据不揭示完整交易者身份，也不能单独证明可成交价格或套利收益。",
        "- 本地 fork 的 approve/swap/revert 验收尚未运行。",
    ])
    return "\n".join(lines) + "\n"
