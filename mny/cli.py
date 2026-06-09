import csv
import json
import sys
import io
from datetime import date, datetime
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm

from .db import init_db, DB_PATH
from . import models

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

console = Console()


def _fmt_amount(amount: float, tx_type: Optional[str] = None) -> str:
    if tx_type == "income" or (tx_type is None and amount >= 0):
        return f"[green]+¥{abs(amount):,.2f}[/green]"
    return f"[red]-¥{abs(amount):,.2f}[/red]"


def _fmt_money(amount: float) -> str:
    if amount >= 0:
        return f"[green]¥{amount:,.2f}[/green]"
    return f"[red]¥{abs(amount):,.2f}[/red]"


@click.group()
@click.version_option(package_name="mny")
def cli():
    """mny - 命令行记账理财工具"""
    init_db()


# ============================================================
# add: 收入 / 支出
# ============================================================
@cli.group()
def add():
    """添加记录：收入或支出"""
    pass


@add.command("income")
@click.argument("amount", type=float)
@click.option("-a", "--account", default="现金", show_default=True, help="账户名称或ID")
@click.option("-c", "--category", default="其他收入", show_default=True, help="收入分类")
@click.option("-d", "--date", "tx_date", default=None, help="日期 YYYY-MM-DD，默认今天")
@click.option("-n", "--note", default=None, help="备注")
@click.option("-t", "--tags", default=None, help="标签，用逗号分隔")
def add_income(amount, account, category, tx_date, note, tags):
    """记录一笔收入

    AMOUNT: 收入金额（必须为正）
    """
    if amount <= 0:
        console.print("[red]✗[/red] 收入金额必须为正数")
        return
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    try:
        tx_id = models.add_transaction("income", amount, account, category, tx_date, note, tag_list)
        console.print(f"[green]✓[/green] 已记录收入 #{tx_id}: {_fmt_amount(amount, 'income')} | {account} | {category}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


@add.command("expense")
@click.argument("amount", type=float)
@click.option("-a", "--account", default="现金", show_default=True, help="账户名称或ID")
@click.option("-c", "--category", default="其他支出", show_default=True, help="支出分类")
@click.option("-d", "--date", "tx_date", default=None, help="日期 YYYY-MM-DD，默认今天")
@click.option("-n", "--note", default=None, help="备注")
@click.option("-t", "--tags", default=None, help="标签，用逗号分隔")
def add_expense(amount, account, category, tx_date, note, tags):
    """记录一笔支出

    AMOUNT: 支出金额（必须为正）
    """
    if amount <= 0:
        console.print("[red]✗[/red] 支出金额必须为正数")
        return
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    try:
        tx_id = models.add_transaction("expense", amount, account, category, tx_date, note, tag_list)
        console.print(f"[green]✓[/green] 已记录支出 #{tx_id}: {_fmt_amount(amount, 'expense')} | {account} | {category}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


# ============================================================
# transfer: 账户间转账
# ============================================================
@cli.group()
def transfer():
    """账户间转账（不算收支，仅同步余额）"""
    pass


@transfer.command("add")
@click.argument("amount", type=float)
@click.option("-f", "--from", "from_acc", required=True, help="转出账户")
@click.option("-t", "--to", "to_acc", required=True, help="转入账户")
@click.option("-d", "--date", "tx_date", default=None, help="日期 YYYY-MM-DD")
@click.option("-n", "--note", default=None, help="备注")
def transfer_add(amount, from_acc, to_acc, tx_date, note):
    """在两账户间转账

    AMOUNT: 转账金额（必须为正）
    """
    if amount <= 0:
        console.print("[red]✗[/red] 转账金额必须为正数")
        return
    try:
        tf_id = models.add_transfer(from_acc, to_acc, amount, tx_date, note)
        console.print(f"[green]✓[/green] 已记录转账 #{tf_id}: {from_acc} → {to_acc} {_fmt_money(amount)}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


@transfer.command("list")
@click.option("--from", "start", default=None, help="起始日期")
@click.option("--to", "end", default=None, help="结束日期")
@click.option("-a", "--account", default=None, help="按账户筛选")
@click.option("-o", "--output", default=None, help="导出到文件（按扩展名识别 csv/json）")
def transfer_list(start, end, account, output):
    """查询转账记录"""
    transfers = models.list_transfers(start, end, account)
    if not transfers:
        console.print("[yellow]没有找到转账记录[/yellow]")
        return

    table = Table(title=f"转账记录（共 {len(transfers)} 条）")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("日期", style="magenta")
    table.add_column("转出", style="red")
    table.add_column("转入", style="green")
    table.add_column("金额", justify="right")
    table.add_column("备注")
    total = 0.0
    for tf in transfers:
        total += tf["amount"]
        table.add_row(
            str(tf["id"]), tf["date"], tf["from_account"], tf["to_account"],
            _fmt_money(tf["amount"]), tf.get("note") or "",
        )
    console.print(table)
    console.print(f"[dim]合计转账: {_fmt_money(total)}[/dim]")

    if output:
        if output.lower().endswith(".json"):
            models.export_report_json(output, transfers)
        else:
            models.export_transfers_csv(output, transfers)
        console.print(f"[green]✓[/green] 已导出到 {output}")


@transfer.command("delete")
@click.argument("tf_id", type=int)
@click.option("-y", "--yes", is_flag=True)
def transfer_delete(tf_id, yes):
    """删除转账记录（会反向恢复余额）"""
    if not yes:
        if not Confirm.confirm(f"确认删除转账 #{tf_id} ？（会恢复两账户余额）", default=False):
            return
    try:
        models.delete_transfer(tf_id)
        console.print(f"[green]✓[/green] 已删除转账 #{tf_id}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


# ============================================================
# recurring: 定期记账
# ============================================================
@cli.group()
def recurring():
    """定期记账（工资、房租、订阅等）"""
    pass


@recurring.command("add")
@click.option("--type", "tx_type", required=True, type=click.Choice(["income", "expense"]), help="收入或支出")
@click.option("--amount", required=True, type=float, help="金额（正数）")
@click.option("-a", "--account", required=True, help="账户")
@click.option("-c", "--category", required=True, help="分类")
@click.option("-f", "--frequency", required=True,
              type=click.Choice(["daily", "weekly", "monthly", "yearly"]),
              help="周期")
@click.option("--day", "interval_day", type=int, default=None,
              help="周期日：周(1-7) / 月(1-31) / 年(1-31)")
@click.option("--start", "start_date", default=None, help="开始日期 YYYY-MM-DD")
@click.option("--end", "end_date", default=None, help="结束日期 YYYY-MM-DD")
@click.option("-n", "--note", default=None, help="备注")
@click.option("-t", "--tags", default=None, help="标签，逗号分隔")
def recurring_add(tx_type, amount, account, category, frequency, interval_day,
                  start_date, end_date, note, tags):
    """新增一条定期记账规则"""
    if amount <= 0:
        console.print("[red]✗[/red] 金额必须为正数")
        return
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    try:
        r_id = models.add_recurring(tx_type, amount, account, category, frequency,
                                    interval_day, start_date, end_date, note, tag_list)
        console.print(f"[green]✓[/green] 已添加定期记账 #{r_id} ({frequency})")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


@recurring.command("list")
@click.option("--all", "show_all", is_flag=True, help="同时显示已停用")
def recurring_list(show_all):
    """列出所有定期记账规则"""
    items = models.list_recurring(active_only=not show_all)
    if not items:
        console.print("[yellow]暂无定期记账规则[/yellow]")
        return
    table = Table(title=f"定期记账（共 {len(items)} 条）")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("状态", justify="center")
    table.add_column("类型", justify="center")
    table.add_column("金额", justify="right")
    table.add_column("账户", style="blue")
    table.add_column("分类", style="yellow")
    table.add_column("周期", style="magenta")
    table.add_column("下次", style="green")
    table.add_column("备注")
    for r in items:
        status = "[green]启用[/green]" if r["active"] else "[dim]停用[/dim]"
        ttype = "[green]收入[/green]" if r["type"] == "income" else "[red]支出[/red]"
        table.add_row(
            str(r["id"]), status, ttype, _fmt_amount(r["amount"], r["type"]),
            r["account"], r["category"], r["frequency"], r["next_date"], r.get("note") or "",
        )
    console.print(table)


@recurring.command("confirm")
@click.argument("r_id", type=int)
@click.option("-d", "--date", "tx_date", default=None, help="指定入账日期")
def recurring_confirm(r_id, tx_date):
    """确认入账一条定期记账（单次）"""
    try:
        tx_id = models.confirm_recurring(r_id, tx_date)
        tx = models.get_transaction(tx_id)
        console.print(f"[green]✓[/green] 已入账 #{tx_id}")
        _print_tx_detail(tx)
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


@recurring.command("run")
@click.option("-d", "--date", "today", default=None, help="截止日期，默认今天")
def recurring_run(today):
    """批量生成所有到期的定期记账"""
    ids = models.generate_recurring(today)
    if ids:
        console.print(f"[green]✓[/green] 已自动生成 {len(ids)} 条定期记账: #{', #'.join(str(i) for i in ids)}")
    else:
        console.print("[yellow]当前没有到期的定期记账[/yellow]")


@recurring.command("toggle")
@click.argument("r_id", type=int)
@click.option("--on", "active", flag_value=True, help="设为启用")
@click.option("--off", "active", flag_value=False, help="设为停用")
def recurring_toggle(r_id, active):
    """启用/停用定期记账"""
    try:
        if active is None:
            models.toggle_recurring(r_id)
        else:
            models.toggle_recurring(r_id, active=active)
        status = "启用" if active else ("停用" if active is False else "切换")
        console.print(f"[green]✓[/green] 定期记账 #{r_id} 已{status}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


@recurring.command("delete")
@click.argument("r_id", type=int)
@click.option("-y", "--yes", is_flag=True)
def recurring_delete(r_id, yes):
    """删除定期记账规则（不影响已入账记录）"""
    if not yes:
        if not Confirm.confirm(f"确认删除定期记账规则 #{r_id} ？", default=False):
            return
    try:
        models.delete_recurring(r_id)
        console.print(f"[green]✓[/green] 已删除定期记账 #{r_id}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


# ============================================================
# list: 查询流水
# ============================================================
@cli.command("list")
@click.option("--from", "start", default=None, help="起始日期 YYYY-MM-DD")
@click.option("--to", "end", default=None, help="结束日期 YYYY-MM-DD")
@click.option("-t", "--type", "tx_type", default=None, type=click.Choice(["income", "expense"]), help="类型")
@click.option("-a", "--account", default=None, help="账户筛选")
@click.option("-c", "--category", default=None, help="分类筛选")
@click.option("-k", "--keyword", default=None, help="关键词搜索（备注或分类）")
@click.option("--tag", default=None, help="标签筛选")
@click.option("-n", "--limit", default=None, type=int, help="显示条数")
@click.option("-o", "--output", default=None, help="导出到文件（.csv 或 .json）")
def list_cmd(start, end, tx_type, account, category, keyword, tag, limit, output):
    """查询交易流水"""
    txs = models.list_transactions(start, end, tx_type, account, category, keyword, tag, limit)
    if not txs:
        console.print("[yellow]没有找到匹配的记录[/yellow]")
        if output:
            console.print("[yellow]无数据可导出[/yellow]")
        return

    table = Table(title=f"交易记录（共 {len(txs)} 条）", show_lines=False)
    table.add_column("ID", justify="right", style="cyan", no_wrap=True)
    table.add_column("日期", style="magenta")
    table.add_column("类型", justify="center")
    table.add_column("金额", justify="right")
    table.add_column("账户", style="blue")
    table.add_column("分类", style="yellow")
    table.add_column("标签", style="green")
    table.add_column("备注", style="white")

    total_income = 0.0
    total_expense = 0.0
    for tx in txs:
        if tx["type"] == "income":
            total_income += tx["amount"]
            ttype = "[green]收入[/green]"
        else:
            total_expense += tx["amount"]
            ttype = "[red]支出[/red]"
        table.add_row(
            str(tx["id"]), tx["date"], ttype,
            _fmt_amount(tx["amount"], tx["type"]),
            tx["account"], tx["category"], ", ".join(tx["tags"]),
            tx.get("note") or "",
        )

    console.print(table)
    footer = (f"合计: 收入 {_fmt_money(total_income)} | "
              f"支出 {_fmt_amount(total_expense, 'expense')} | "
              f"净结余 {_fmt_money(total_income - total_expense)}")
    console.print(Panel(footer, border_style="dim"))

    if output:
        if output.lower().endswith(".json"):
            models.export_transactions_json(output, txs)
        else:
            models.export_transactions_csv(output, txs)
        console.print(f"[green]✓[/green] 已导出 {len(txs)} 条到 {output}")


# ============================================================
# edit: 修改 / 删除
# ============================================================
@cli.group()
def edit():
    """修改或删除账目"""
    pass


@edit.command("update")
@click.argument("tx_id", type=int)
@click.option("--type", "tx_type", default=None, type=click.Choice(["income", "expense"]), help="类型")
@click.option("--amount", default=None, type=float, help="金额（正数）")
@click.option("-a", "--account", default=None, help="账户")
@click.option("-c", "--category", default=None, help="分类")
@click.option("-d", "--date", "tx_date", default=None, help="日期")
@click.option("-n", "--note", default=None, help="备注")
@click.option("-t", "--tags", default=None, help="标签，逗号分隔（覆盖原标签）")
def edit_update(tx_id, tx_type, amount, account, category, tx_date, note, tags):
    """修改交易记录

    TX_ID: 交易ID
    """
    if amount is not None and amount <= 0:
        console.print("[red]✗[/red] 金额必须为正数")
        return
    tag_list = [t.strip() for t in tags.split(",")] if tags is not None else None
    try:
        models.update_transaction(tx_id, tx_type, amount, account, category, tx_date, note, tag_list)
        tx = models.get_transaction(tx_id)
        console.print(f"[green]✓[/green] 已更新 #{tx_id}")
        _print_tx_detail(tx)
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


@edit.command("delete")
@click.argument("tx_id", type=int)
@click.option("-y", "--yes", is_flag=True, help="不提示确认")
def edit_delete(tx_id, yes):
    """删除交易记录"""
    tx = models.get_transaction(tx_id)
    if not tx:
        console.print(f"[red]✗[/red] 交易不存在: #{tx_id}")
        return
    _print_tx_detail(tx)
    if not yes:
        if not Confirm.confirm("确认删除这条记录？", default=False):
            console.print("[yellow]已取消[/yellow]")
            return
    try:
        models.delete_transaction(tx_id)
        console.print(f"[green]✓[/green] 已删除 #{tx_id}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


def _print_tx_detail(tx):
    table = Table(show_header=False, border_style="dim")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("ID", str(tx["id"]))
    table.add_row("日期", tx["date"])
    table.add_row("类型", "收入" if tx["type"] == "income" else "支出")
    table.add_row("金额", _fmt_amount(tx["amount"], tx["type"]))
    table.add_row("账户", tx["account"])
    table.add_row("分类", tx["category"])
    table.add_row("标签", ", ".join(tx["tags"]))
    table.add_row("备注", tx.get("note") or "")
    console.print(table)


# ============================================================
# budget: 预算
# ============================================================
@cli.group()
def budget():
    """管理月度分类预算"""
    pass


@budget.command("set")
@click.argument("category")
@click.argument("amount", type=float)
@click.option("-y", "--year", type=int, default=None, help="年份，默认今年")
@click.option("-m", "--month", type=int, default=None, help="月份，默认本月")
def budget_set(category, amount, year, month):
    """设置月度预算"""
    if amount <= 0:
        console.print("[red]✗[/red] 预算金额必须为正数")
        return
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month
    try:
        models.set_budget(category, year, month, amount)
        console.print(f"[green]✓[/green] 已设置 {year}-{month:02d} {category} 预算: ¥{amount:,.2f}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


@budget.command("list")
@click.option("-y", "--year", type=int, default=None, help="年份，默认今年")
@click.option("-m", "--month", type=int, default=None, help="月份，默认本月")
def budget_list(year, month):
    """查看月度预算及使用情况"""
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    budgets = models.list_budgets(year, month)
    if not budgets:
        console.print(f"[yellow]{year}-{month:02d} 暂无预算设置[/yellow]")
        return

    table = Table(title=f"{year}-{month:02d} 预算概览")
    table.add_column("分类", style="yellow")
    table.add_column("预算", justify="right", style="cyan")
    table.add_column("已用", justify="right")
    table.add_column("剩余", justify="right")
    table.add_column("进度", justify="center")

    for b in budgets:
        pct = (b["spent"] / b["amount"] * 100) if b["amount"] > 0 else 0
        if pct >= 100:
            status = f"[red]超支 {pct - 100:.0f}%[/red]"
            remaining_style = "red"
        elif pct >= 80:
            status = f"[yellow]警告 {pct:.0f}%[/yellow]"
            remaining_style = "yellow"
        else:
            status = f"[green]正常 {pct:.0f}%[/green]"
            remaining_style = "green"

        bar_len = 20
        filled = int(min(pct / 100, 1) * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        if pct >= 100:
            bar = f"[red]{bar}[/red]"
        elif pct >= 80:
            bar = f"[yellow]{bar}[/yellow]"
        else:
            bar = f"[green]{bar}[/green]"

        table.add_row(
            b["category_name"],
            f"¥{b['amount']:,.2f}",
            f"¥{b['spent']:,.2f}",
            f"[{remaining_style}]¥{b['remaining']:,.2f}[/{remaining_style}]",
            f"{bar} {status}",
        )

    console.print(table)


# ============================================================
# report: 报表
# ============================================================
@cli.group()
def report():
    """生成报表：周报、月报、年报等"""
    pass


def _maybe_export_report(data, output):
    if not output:
        return
    if output.lower().endswith(".json"):
        models.export_report_json(output, data)
    else:
        models.export_report_csv(output, data)
    console.print(f"[green]✓[/green] 已导出报表到 {output}")


def _show_pending_recurring(year, month):
    pending = models.get_pending_recurring(year, month)
    if not pending:
        return
    table = Table(title=f"🔔 {year}-{month:02d} 待入账的固定收支（确认后入账）")
    table.add_column("规则ID", justify="right", style="cyan")
    table.add_column("预计日期", style="magenta")
    table.add_column("类型", justify="center")
    table.add_column("金额", justify="right")
    table.add_column("账户", style="blue")
    table.add_column("分类", style="yellow")
    table.add_column("周期", style="dim")
    table.add_column("备注")
    income = 0.0
    expense = 0.0
    for p in pending:
        if p["type"] == "income":
            income += p["amount"]
            ttype = "[green]收入[/green]"
        else:
            expense += p["amount"]
            ttype = "[red]支出[/red]"
        table.add_row(
            str(p["id"]), p["date"], ttype, _fmt_amount(p["amount"], p["type"]),
            p["account"], p["category"], p["frequency"], p.get("note") or "",
        )
    console.print(table)
    console.print(
        f"[dim]待入账合计: 收入 {_fmt_money(income)} | "
        f"支出 {_fmt_money(expense)} | 净影响 {_fmt_money(income - expense)}[/dim]"
    )


@report.command("weekly")
@click.option("-o", "--output", default=None, help="导出（csv/json）")
def report_weekly(output):
    """本周收支概览"""
    data = models.get_weekly_summary()
    console.print(Panel(
        f"报告周期: [bold]{data['start']}[/bold] 至 [bold]{data['end']}[/bold]\n"
        f"收入: {_fmt_money(data['income'])}  "
        f"支出: {_fmt_amount(data['expense'], 'expense')}  "
        f"净结余: {_fmt_money(data['net'])}",
        title="📊 周报表",
        border_style="blue",
    ))
    _print_category_breakdown(data["by_category"])
    _maybe_export_report(data, output)


@report.command("monthly")
@click.option("-y", "--year", type=int, default=None, help="年份，默认今年")
@click.option("-m", "--month", type=int, default=None, help="月份，默认本月")
@click.option("-o", "--output", default=None, help="导出（csv/json）")
def report_monthly(year, month, output):
    """月度收支报表"""
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    data = models.get_monthly_summary(year, month)
    console.print(Panel(
        f"报告周期: [bold]{year}-{month:02d}[/bold]\n"
        f"收入: {_fmt_money(data['income'])}  "
        f"支出: {_fmt_amount(data['expense'], 'expense')}  "
        f"净结余: {_fmt_money(data['net'])}",
        title=f"📊 {year}-{month:02d} 月报表",
        border_style="blue",
    ))
    _print_category_breakdown(data["by_category"])
    _show_pending_recurring(year, month)
    _maybe_export_report(data, output)


@report.command("yearly")
@click.option("-y", "--year", type=int, default=None, help="年份，默认今年")
@click.option("-o", "--output", default=None, help="导出（csv/json）")
def report_yearly(year, output):
    """年度收支报表"""
    today = date.today()
    if year is None:
        year = today.year

    data = models.get_yearly_summary(year)
    console.print(Panel(
        f"报告周期: [bold]{year}[/bold] 全年\n"
        f"收入: {_fmt_money(data['income'])}  "
        f"支出: {_fmt_amount(data['expense'], 'expense')}  "
        f"净结余: {_fmt_money(data['net'])}",
        title=f"📊 {year} 年报表",
        border_style="blue",
    ))
    _print_category_breakdown(data["by_category"])

    month_data = {}
    for m in data["by_month"]:
        key = m["month"]
        if key not in month_data:
            month_data[key] = {"income": 0, "expense": 0}
        if m["type"] == "income":
            month_data[key]["income"] = m["total"]
        else:
            month_data[key]["expense"] = m["total"]

    table = Table(title=f"{year} 分月趋势")
    table.add_column("月份", style="cyan", justify="center")
    table.add_column("收入", justify="right")
    table.add_column("支出", justify="right")
    table.add_column("净结余", justify="right")

    for m in sorted(month_data.keys()):
        d = month_data[m]
        net = d["income"] - d["expense"]
        table.add_row(
            f"{int(m)}月",
            _fmt_money(d["income"]),
            _fmt_amount(d["expense"], "expense"),
            _fmt_money(net),
        )
    console.print(table)
    _maybe_export_report(data, output)


@report.command("balance")
@click.option("-o", "--output", default=None, help="导出（csv/json）")
def report_balance(output):
    """账户余额概览（含转账统计）"""
    accounts = models.get_account_balances()
    if not accounts:
        console.print("[yellow]暂无账户[/yellow]")
        return

    enriched = []
    for acc in accounts:
        tf = models.get_account_transfer_stats(acc["id"])
        d = dict(acc)
        d["transfer_in"] = tf["transfer_in"]
        d["transfer_out"] = tf["transfer_out"]
        enriched.append(d)

    table = Table(title="💰 账户余额概览")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("账户", style="blue")
    table.add_column("类型", style="magenta")
    table.add_column("余额", justify="right")
    table.add_column("累计收入", justify="right")
    table.add_column("累计支出", justify="right")
    table.add_column("转入", justify="right", style="green")
    table.add_column("转出", justify="right", style="red")

    total = 0.0
    for acc in enriched:
        total += acc["balance"]
        table.add_row(
            str(acc["id"]), acc["name"], acc["type"],
            _fmt_money(acc["balance"]),
            _fmt_money(acc["total_income"]),
            _fmt_amount(acc["total_expense"], "expense"),
            _fmt_money(acc["transfer_in"]),
            _fmt_amount(acc["transfer_out"], "expense"),
        )

    console.print(table)
    console.print(f"\n[bold]总资产:[/bold] {_fmt_money(total)}")

    if output:
        if output.lower().endswith(".json"):
            models.export_report_json(output, enriched)
        else:
            models.export_report_csv(output, {"accounts": enriched, "total_assets": total})
        console.print(f"[green]✓[/green] 已导出到 {output}")


def _print_category_breakdown(by_category):
    income_total = sum(c["total"] for c in by_category if c["type"] == "income")
    expense_total = sum(c["total"] for c in by_category if c["type"] == "expense")

    income_cats = [c for c in by_category if c["type"] == "income"]
    expense_cats = [c for c in by_category if c["type"] == "expense"]

    if income_cats:
        table = Table(title="💵 收入分类占比")
        table.add_column("分类", style="green")
        table.add_column("金额", justify="right")
        table.add_column("占比", justify="right")
        table.add_column("分布", justify="left")
        for c in sorted(income_cats, key=lambda x: -x["total"]):
            pct = (c["total"] / income_total * 100) if income_total > 0 else 0
            bar_len = 20
            filled = int(pct / 100 * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)
            table.add_row(c["category"], _fmt_amount(c["total"], c["type"]), f"{pct:.1f}%", f"[green]{bar}[/green]")
        console.print(table)

    if expense_cats:
        table = Table(title="💸 支出分类占比")
        table.add_column("分类", style="red")
        table.add_column("金额", justify="right")
        table.add_column("占比", justify="right")
        table.add_column("分布", justify="left")
        for c in sorted(expense_cats, key=lambda x: -x["total"]):
            pct = (c["total"] / expense_total * 100) if expense_total > 0 else 0
            bar_len = 20
            filled = int(pct / 100 * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)
            table.add_row(c["category"], _fmt_amount(c["total"], c["type"]), f"{pct:.1f}%", f"[red]{bar}[/red]")
        console.print(table)


# ============================================================
# import: 导入（改进版）
# ============================================================
@cli.command("import")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("-f", "--format", "fmt", default="csv",
              type=click.Choice(["csv", "json"]), show_default=True, help="文件格式")
@click.option("--non-interactive", is_flag=True, help="非交互模式（分类不匹配直接跳过）")
def import_cmd(file, fmt, non_interactive):
    """导入账单文件（CSV或JSON），自动合并重复、拦截负数、分类不匹配可交互重选

    CSV字段: type(income/expense),amount,account,category,date(YYYY-MM-DD),note,tags(逗号分隔)
    """
    try:
        records = []
        if fmt == "csv":
            with open(file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append(dict(row))
        else:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    records = data
                else:
                    raise ValueError("JSON 必须是数组格式")

        if not records:
            console.print("[yellow]文件为空，没有可导入的记录[/yellow]")
            return

        def on_mismatch(tx, wrong_type, alt_cats):
            console.print(
                f"\n[yellow]⚠[/yellow] 行数据类型不匹配: "
                f"分类 '{tx['category']}' 是 [red]{wrong_type}[/red]，"
                f"但这条是 [green]{tx['type']}[/green]（金额 ¥{tx['amount']}, {tx.get('note') or '无备注'}）"
            )
            if non_interactive:
                console.print("[dim]非交互模式，已跳过[/dim]")
                return None
            choices = [c["name"] for c in alt_cats]
            console.print(f"可选的 {tx['type']} 分类: {', '.join(choices)}")
            answer = Prompt.ask(
                f"请选择正确分类（直接回车跳过，或输入新分类名将自动创建）",
                default="",
                show_default=False,
            )
            return answer.strip() if answer.strip() else None

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task(f"正在导入 {len(records)} 条记录...", total=None)
            added, skipped, errors = models.bulk_import_v2(records, on_mismatch)

        console.print(f"[green]✓[/green] 导入完成: 新增 {added} 条，跳过 {skipped} 条")
        if errors:
            console.print("[yellow]以下记录被跳过:[/yellow]")
            for idx, msg in errors[:20]:
                console.print(f"  行 {idx + 1}: {msg}")
            if len(errors) > 20:
                console.print(f"  ... 其余 {len(errors) - 20} 条省略")
    except Exception as e:
        console.print(f"[red]✗[/red] 导入失败: {e}")


# ============================================================
# backup: 数据库备份/恢复
# ============================================================
@cli.group()
def backup():
    """数据库备份与恢复"""
    pass


@backup.command("save")
@click.option("-d", "--dir", "target_dir", default=None, help="备份目录，默认 ~/.mny/backups")
def backup_save(target_dir):
    """备份当前数据库"""
    try:
        path = models.backup_database(target_dir)
        console.print(f"[green]✓[/green] 已备份到: {path}")
    except Exception as e:
        console.print(f"[red]✗[/red] 备份失败: {e}")


@backup.command("list")
@click.option("-d", "--dir", "backup_dir", default=None, help="备份目录")
def backup_list(backup_dir):
    """列出所有备份"""
    backups = models.list_backups(backup_dir)
    if not backups:
        console.print("[yellow]暂无备份[/yellow]")
        return
    table = Table(title="数据库备份")
    table.add_column("文件名", style="cyan")
    table.add_column("大小", justify="right")
    table.add_column("修改时间", style="magenta")
    table.add_column("路径", style="dim")
    for b in backups:
        size_kb = b["size"] / 1024
        table.add_row(
            b["name"],
            f"{size_kb:,.1f} KB",
            b["modified"],
            b["file"],
        )
    console.print(table)


@backup.command("restore")
@click.argument("backup_file", type=click.Path(exists=True, dir_okay=False))
@click.option("-y", "--yes", is_flag=True)
def backup_restore(backup_file, yes):
    """从备份恢复数据库（会自动备份当前库）"""
    if not yes:
        if not Confirm.confirm(
            f"将用 {backup_file} 覆盖当前数据库（当前库会自动备份），确认？",
            default=False,
        ):
            return
    try:
        models.restore_database(backup_file)
        console.print(f"[green]✓[/green] 已从 {backup_file} 恢复数据库")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


# ============================================================
# export: 单独的导出入口
# ============================================================
@cli.group()
def export():
    """导出流水/报表为 CSV 或 JSON（list/report 也自带 -o）"""
    pass


@export.command("transactions")
@click.option("-o", "--output", required=True, help="输出文件（.csv 或 .json）")
@click.option("--from", "start", default=None)
@click.option("--to", "end", default=None)
@click.option("-t", "--type", "tx_type", default=None, type=click.Choice(["income", "expense"]))
@click.option("-a", "--account", default=None)
@click.option("-c", "--category", default=None)
@click.option("-k", "--keyword", default=None)
@click.option("--tag", default=None)
def export_transactions(output, start, end, tx_type, account, category, keyword, tag):
    """导出交易流水"""
    txs = models.list_transactions(start, end, tx_type, account, category, keyword, tag)
    if not txs:
        console.print("[yellow]无数据可导出[/yellow]")
        return
    if output.lower().endswith(".json"):
        models.export_transactions_json(output, txs)
    else:
        models.export_transactions_csv(output, txs)
    console.print(f"[green]✓[/green] 已导出 {len(txs)} 条到 {output}")


# ============================================================
# account / category / info
# ============================================================
@cli.group()
def account():
    """管理账户"""
    pass


@account.command("list")
def account_list():
    """列出所有账户"""
    accounts = models.list_accounts()
    table = Table(title="账户列表")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("名称", style="blue")
    table.add_column("类型", style="magenta")
    table.add_column("余额", justify="right")
    for a in accounts:
        table.add_row(str(a["id"]), a["name"], a["type"], _fmt_money(a["balance"]))
    console.print(table)


@account.command("add")
@click.argument("name")
@click.option("-t", "--type", "atype", default="cash", show_default=True, help="账户类型")
@click.option("-b", "--balance", default=0.0, type=float, help="初始余额")
def account_add(name, atype, balance):
    """新增账户"""
    models.add_account(name, atype, balance)
    console.print(f"[green]✓[/green] 已添加账户: {name} ({_fmt_money(balance)})")


@cli.group()
def category():
    """管理分类"""
    pass


@category.command("list")
@click.option("-t", "--type", "ctype", default=None, type=click.Choice(["income", "expense"]), help="按类型筛选")
def category_list(ctype):
    """列出所有分类"""
    cats = models.list_categories(ctype)
    table = Table(title="分类列表")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("名称", style="yellow")
    table.add_column("类型", style="magenta")
    for c in cats:
        ttype = "[green]收入[/green]" if c["type"] == "income" else "[red]支出[/red]"
        table.add_row(str(c["id"]), c["name"], ttype)
    console.print(table)


@category.command("add")
@click.argument("name")
@click.option("-t", "--type", "ctype", required=True, type=click.Choice(["income", "expense"]), help="分类类型")
def category_add(name, ctype):
    """新增分类"""
    models.add_category(name, ctype)
    ttype = "收入" if ctype == "income" else "支出"
    console.print(f"[green]✓[/green] 已添加{ttype}分类: {name}")


@cli.command("info")
def info():
    """显示工具信息"""
    console.print(Panel(
        f"[bold]mny[/bold] - 命令行记账理财工具 v0.2.0\n\n"
        f"数据库路径: [cyan]{DB_PATH}[/cyan]\n"
        f"使用 '[bold]mny --help[/bold]' 查看全部命令\n"
        f"新功能: transfer 转账 / recurring 定期记账 / backup 备份恢复 / export 导出",
        title="💰 mny",
        border_style="green",
    ))


if __name__ == "__main__":
    cli()
