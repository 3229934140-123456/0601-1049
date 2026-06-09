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
@click.option("-p", "--projects", default=None, help="项目，用逗号分隔")
def add_income(amount, account, category, tx_date, note, tags, projects):
    """记录一笔收入

    AMOUNT: 收入金额（必须为正）
    """
    if amount <= 0:
        console.print("[red]✗[/red] 收入金额必须为正数")
        return
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    proj_list = [p.strip() for p in projects.split(",")] if projects else None
    try:
        tx_id = models.add_transaction("income", amount, account, category, tx_date, note, tag_list, proj_list)
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
@click.option("-p", "--projects", default=None, help="项目，用逗号分隔")
def add_expense(amount, account, category, tx_date, note, tags, projects):
    """记录一笔支出

    AMOUNT: 支出金额（必须为正）
    """
    if amount <= 0:
        console.print("[red]✗[/red] 支出金额必须为正数")
        return
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    proj_list = [p.strip() for p in projects.split(",")] if projects else None
    try:
        tx_id = models.add_transaction("expense", amount, account, category, tx_date, note, tag_list, proj_list)
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
        if not Confirm.ask(f"确认删除转账 #{tf_id} ？（会恢复两账户余额）", default=False):
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
        if active is None:
            status = "切换"
        else:
            status = "启用" if active else "停用"
        console.print(f"[green]✓[/green] 定期记账 #{r_id} 已{status}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


@recurring.command("delete")
@click.argument("r_id", type=int)
@click.option("-y", "--yes", is_flag=True)
def recurring_delete(r_id, yes):
    """删除定期记账规则（不影响已入账记录）"""
    if not yes:
        if not Confirm.ask(f"确认删除定期记账规则 #{r_id} ？", default=False):
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
@click.option("--project", default=None, help="项目筛选")
@click.option("-n", "--limit", default=None, type=int, help="显示条数")
@click.option("-o", "--output", default=None, help="导出到文件（.csv 或 .json）")
def list_cmd(start, end, tx_type, account, category, keyword, tag, project, limit, output):
    """查询交易流水"""
    txs = models.list_transactions(start, end, tx_type, account, category, keyword, tag, project, limit)
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
    table.add_column("项目", style="cyan")
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
            tx["account"], tx["category"], ", ".join(tx.get("tags", [])),
            ", ".join(tx.get("projects", [])),
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
@click.option("-p", "--projects", default=None, help="项目，逗号分隔（覆盖原项目）")
def edit_update(tx_id, tx_type, amount, account, category, tx_date, note, tags, projects):
    """修改交易记录

    TX_ID: 交易ID
    """
    if amount is not None and amount <= 0:
        console.print("[red]✗[/red] 金额必须为正数")
        return
    tag_list = [t.strip() for t in tags.split(",")] if tags is not None else None
    proj_list = [p.strip() for p in projects.split(",")] if projects is not None else None

    existing = models.get_transaction(tx_id)
    if not existing:
        console.print(f"[red]✗[/red] 交易不存在: #{tx_id}")
        return

    new_type = tx_type if tx_type else existing["type"]
    new_category = category
    if tx_type and tx_type != existing["type"]:
        old_cat_type = existing["type"]
        if category is None:
            console.print(
                f"[yellow]⚠[/yellow] 类型从 [bold]{old_cat_type}[/bold] 改为 [bold]{tx_type}[/bold]，"
                f"原分类 '{existing['category']}' 属于 {old_cat_type}，需要重新选择 {tx_type} 分类"
            )
            alt_cats = models.list_categories(tx_type)
            names = [c["name"] for c in alt_cats]
            console.print(f"可选的 {tx_type} 分类: {', '.join(names)}")
            answer = Prompt.ask(
                f"请选择一个 {tx_type} 分类（或输入新分类名自动创建）",
                default=names[0] if names else "",
                show_default=False,
            )
            new_category = answer.strip() if answer.strip() else None
            if not new_category:
                console.print("[yellow]已取消[/yellow]")
                return
        else:
            cat_check = models.get_category(category, tx_type)
            if not cat_check:
                console.print(
                    f"[yellow]⚠[/yellow] 指定的分类 '{category}' 不是 {tx_type} 类型"
                )
                alt_cats = models.list_categories(tx_type)
                names = [c["name"] for c in alt_cats]
                console.print(f"可选的 {tx_type} 分类: {', '.join(names)}")
                answer = Prompt.ask(
                    f"请选择一个 {tx_type} 分类（或输入新分类名自动创建）",
                    default=names[0] if names else "",
                    show_default=False,
                )
                new_category = answer.strip() if answer.strip() else None
                if not new_category:
                    console.print("[yellow]已取消[/yellow]")
                    return

    try:
        models.update_transaction(tx_id, tx_type, amount, account, new_category, tx_date, note, tag_list, proj_list)
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
        if not Confirm.ask("确认删除这条记录？", default=False):
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
    table.add_row("标签", ", ".join(tx.get("tags", [])))
    table.add_row("项目", ", ".join(tx.get("projects", [])))
    table.add_row("备注", tx.get("note") or "")
    console.print(table)


# ============================================================
# budget: 预算（多维度）
# ============================================================
@cli.group()
def budget():
    """管理月度预算（支持分类/账户/标签/项目多维度）"""
    pass


@budget.command("set")
@click.option("-s", "--scope", default="category",
              type=click.Choice(["category", "account", "tag", "project"]),
              show_default=True, help="预算维度")
@click.argument("key")
@click.argument("amount", type=float)
@click.option("-y", "--year", type=int, default=None, help="年份，默认今年")
@click.option("-m", "--month", type=int, default=None, help="月份，默认本月")
def budget_set(scope, key, amount, year, month):
    """设置月度预算（支持分类/账户/标签/项目）

    KEY: 维度对应的名称，例如 '餐饮'（分类）/ '银行卡'（账户）/ '出差'（标签）
    """
    if amount < 0:
        console.print("[red]✗[/red] 预算金额不能为负数")
        return
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month
    try:
        models.set_budget(scope, key, year, month, amount)
        models.refresh_carry_over(year, month)
        console.print(f"[green]✓[/green] 已设置 {year}-{month:02d} {scope}={key} 预算: ¥{amount:,.2f}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


@budget.command("refresh")
@click.option("-y", "--year", type=int, default=None, help="年份，默认今年")
@click.option("-m", "--month", type=int, default=None, help="月份，默认本月")
def budget_refresh(year, month):
    """刷新本月所有预算的上月结转字段"""
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month
    updated = models.refresh_carry_over(year, month)
    console.print(f"[green]✓[/green] 刷新完成，更新了 {updated} 条预算的上月结转")


@budget.command("list")
@click.option("-y", "--year", type=int, default=None, help="年份，默认今年")
@click.option("-m", "--month", type=int, default=None, help="月份，默认本月")
def budget_list(year, month):
    """查看月度预算及使用情况、月底预测、固定支出占用（含上月结转）"""
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    models.refresh_carry_over(year, month)
    analysis = models.get_budget_analysis_with_carry(year, month)
    budgets = analysis["budgets"]
    if not budgets:
        console.print(f"[yellow]{year}-{month:02d} 暂无预算设置[/yellow]")
        return

    table = Table(title=f"{year}-{month:02d} 预算概览（已过 {analysis['days_passed']} 天，剩 {analysis['days_remaining']} 天）")
    table.add_column("维度", style="cyan")
    table.add_column("对象", style="yellow")
    table.add_column("本月预算", justify="right", style="cyan")
    table.add_column("上月结转", justify="right", style="magenta")
    table.add_column("实际可用", justify="right")
    table.add_column("已用", justify="right")
    table.add_column("待入账", justify="right", style="magenta")
    table.add_column("剩余", justify="right")
    table.add_column("日均", justify="right", style="dim")
    table.add_column("月底预测", justify="right")
    table.add_column("状态", justify="center")

    for b in budgets:
        effective = b["effective_budget"]
        pct = (b["spent"] / effective * 100) if effective > 0 else 0
        if b["will_overrun"]:
            status = f"[red]预计超支[/red]"
            remaining_style = "red"
        elif pct >= 100:
            status = f"[red]已超支 {pct - 100:.0f}%[/red]"
            remaining_style = "red"
        elif pct >= 80:
            status = f"[yellow]警告 {pct:.0f}%[/yellow]"
            remaining_style = "yellow"
        else:
            status = f"[green]正常 {pct:.0f}%[/green]"
            remaining_style = "green"

        carry_style = "green" if b["carry_over"] >= 0 else "red"
        predicted_str = _fmt_money(b["projected_total"])
        if b["will_overrun"]:
            predicted_str += f" [red](超 ¥{b['projected_overrun']:,.2f})[/red]"

        table.add_row(
            b["scope"], b["scope_key"],
            f"¥{b['amount']:,.2f}",
            f"[{carry_style}]¥{b['carry_over']:+,.2f}[/{carry_style}]",
            f"¥{effective:,.2f}",
            f"¥{b['spent']:,.2f}",
            f"¥{b['recurring_pending']:,.2f}" if b["recurring_pending"] > 0 else "-",
            f"[{remaining_style}]¥{b['available_effective']:,.2f}[/{remaining_style}]",
            f"¥{b['daily_avg']:,.2f}",
            predicted_str,
            status,
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


def _show_budget_analysis(year, month):
    analysis = models.get_budget_analysis_with_carry(year, month)
    budgets = analysis["budgets"]
    if not budgets:
        return
    table = Table(title=f"🎯 {year}-{month:02d} 预算状态 & 月底预测")
    table.add_column("维度", style="cyan")
    table.add_column("对象", style="yellow")
    table.add_column("本月预算", justify="right", style="cyan")
    table.add_column("上月结转", justify="right", style="magenta")
    table.add_column("实际可用", justify="right")
    table.add_column("已用", justify="right")
    table.add_column("固定支出待入账", justify="right", style="magenta")
    table.add_column("剩余", justify="right")
    table.add_column("月底预测", justify="right")
    for b in budgets:
        carry_style = "green" if b["carry_over"] >= 0 else "red"
        predicted_str = _fmt_money(b["projected_total"])
        if b["will_overrun"]:
            predicted_str += f" [red]超支¥{b['projected_overrun']:,.2f}[/red]"
        eff_style = "red" if b["available_effective"] < 0 else "green"
        table.add_row(
            b["scope"], b["scope_key"],
            f"¥{b['amount']:,.2f}",
            f"[{carry_style}]¥{b['carry_over']:+,.2f}[/{carry_style}]",
            f"¥{b['effective_budget']:,.2f}",
            f"¥{b['spent']:,.2f}",
            f"¥{b['recurring_pending']:,.2f}" if b["recurring_pending"] > 0 else "-",
            f"[{eff_style}]¥{b['available_effective']:,.2f}[/{eff_style}]",
            predicted_str,
        )
    console.print(table)


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

    models.refresh_carry_over(year, month)
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
    _show_budget_analysis(year, month)
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
    nw = models.get_current_net_worth()
    console.print(f"\n[bold]总资产:[/bold] {_fmt_money(nw['total_assets'])}"
                  f"   [bold red]总负债:[/bold red] {_fmt_money(nw['total_liability'])}"
                  f"   [bold green]净资产:[/bold green] {_fmt_money(nw['net_worth'])}")

    # 净资产趋势
    trend = models.get_net_worth_trend(months=6)
    if any(x is not None for x in trend["net_worth"]):
        t = Table(title="📈 最近 6 个月净资产趋势（含估算）")
        t.add_column("月份", style="cyan", justify="center")
        t.add_column("资产", justify="right")
        t.add_column("负债", justify="right", style="red")
        t.add_column("净资产", justify="right", style="bold green")
        t.add_column("环比变化", justify="right")
        prev_net = None
        for i, p in enumerate(trend["periods"]):
            assets = trend["assets"][i]
            liab = trend["liabilities"][i]
            net = trend["net_worth"][i]
            if assets is None:
                t.add_row(p, "-", "-", "-", "-")
                continue
            delta_s = "-"
            if prev_net is not None:
                delta = net - prev_net
                delta_s = _fmt_amount(abs(delta), "income" if delta > 0 else "expense")
            t.add_row(p, _fmt_money(assets), _fmt_money(liab), _fmt_money(net), delta_s)
            prev_net = net
        console.print(t)

    if output:
        if output.lower().endswith(".json"):
            models.export_report_json(output, {
                "accounts": enriched,
                "total_assets": nw["total_assets"],
                "total_liability": nw["total_liability"],
                "net_worth": nw["net_worth"],
                "trend": trend,
            })
        else:
            rows = [dict(a) for a in enriched]
            rows.append({
                "id": "_NET_WORTH_",
                "name": "_NET_WORTH_",
                "type": "_TOTAL_",
                "balance": round(nw["net_worth"], 2),
                "total_assets": round(nw["total_assets"], 2),
                "total_liability": round(nw["total_liability"], 2),
            })
            for i, p in enumerate(trend["periods"]):
                if trend["assets"][i] is not None:
                    rows.append({
                        "id": "_TREND_",
                        "name": p,
                        "type": "_TREND_",
                        "balance": round(trend["net_worth"][i], 2),
                        "total_assets": round(trend["assets"][i], 2),
                        "total_liability": round(trend["liabilities"][i], 2),
                    })
            models.export_report_csv(output, rows)
        console.print(f"[green]✓[/green] 已导出到 {output}")


@report.command("trend")
@click.option("-n", "--months", type=int, default=3, show_default=True, help="最近几个月")
@click.option("-s", "--scope", type=click.Choice(["category", "account", "tag", "project"]),
              default="category", show_default=True, help="按什么维度聚合")
@click.option("-k", "--key", "scope_key", default=None, help="只看某个具体维度值（如 '餐饮'）")
@click.option("-o", "--output", default=None, help="导出 CSV/JSON")
def report_trend(months, scope, scope_key, output):
    """最近 N 个月按分类/账户/标签/项目的收支趋势"""
    if months < 1:
        months = 1
    data = models.get_trend(months=months, scope=scope, scope_key=scope_key)
    periods = data["periods"]
    series = data["series"]
    if not series:
        console.print(f"[yellow]最近 {months} 个月按 {scope} 维度没有数据[/yellow]")
        return

    table = Table(title=f"📈 最近 {months} 个月 {scope + ('=' + scope_key if scope_key else '')} 收支趋势")
    table.add_column(scope, style="cyan")
    table.add_column("类型", justify="center")
    for p in periods:
        table.add_column(p, justify="right")
    table.add_column("合计", justify="right", style="bold")

    for s in series:
        incomes = s["income"]
        expenses = s["expense"]
        income_total = sum(incomes)
        expense_total = sum(expenses)
        if income_total > 0:
            table.add_row(
                s["name"], "[green]收入[/green]",
                *[_fmt_money(x) if x > 0 else "-" for x in incomes],
                _fmt_money(income_total),
            )
        if expense_total > 0:
            table.add_row(
                s["name"], "[red]支出[/red]",
                *[_fmt_amount(x, "expense") if x > 0 else "-" for x in expenses],
                _fmt_amount(expense_total, "expense"),
            )

    # 合计行
    pi = data["period_income"]
    pe = data["period_expense"]
    if any(pi) or any(pe):
        table.add_section()
        table.add_row(
            "合计", "[green]收入[/green]",
            *[_fmt_money(x) if x > 0 else "-" for x in pi],
            _fmt_money(sum(pi)),
        )
        table.add_row(
            "合计", "[red]支出[/red]",
            *[_fmt_amount(x, "expense") if x > 0 else "-" for x in pe],
            _fmt_amount(sum(pe), "expense"),
        )

    console.print(table)

    if output:
        if output.lower().endswith(".json"):
            models.export_report_json(output, data)
        else:
            rows = []
            for s in series:
                for i, p in enumerate(periods):
                    if s["income"][i] > 0:
                        rows.append({
                            scope: s["name"], "period": p, "type": "income",
                            "amount": round(s["income"][i], 2),
                        })
                    if s["expense"][i] > 0:
                        rows.append({
                            scope: s["name"], "period": p, "type": "expense",
                            "amount": round(s["expense"][i], 2),
                        })
            for i, p in enumerate(periods):
                if pi[i] > 0:
                    rows.append({scope: "_TOTAL", "period": p, "type": "income", "amount": round(pi[i], 2)})
                if pe[i] > 0:
                    rows.append({scope: "_TOTAL", "period": p, "type": "expense", "amount": round(pe[i], 2)})
            import csv as _csv
            with open(output, "w", encoding="utf-8-sig", newline="") as f:
                if rows:
                    fields = list(rows[0].keys())
                    writer = _csv.DictWriter(f, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(rows)
                else:
                    f.write("")
        console.print(f"[green]✓[/green] 已导出趋势到 {output}")


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
# reconcile: 对账
# ============================================================
@cli.group()
def reconcile():
    """对账/校准：对比银行流水与 mny 内部记录"""
    pass


def _read_reconcile_file(file, fmt):
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
    return records


@reconcile.command("run")
@click.argument("account")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("-f", "--format", "fmt", default="csv",
              type=click.Choice(["csv", "json"]), show_default=True, help="文件格式")
@click.option("-y", "--yes", is_flag=True, help="非交互：直接对缺失进行批量补记")
@click.option("--default-category", default=None,
              help="批量补记缺失记录时使用的默认分类")
@click.option("-b", "--balance", type=float, default=None,
              help="银行/平台导出的期末余额，对账后展示差额并可校准")
@click.option("--show-dupes", is_flag=True,
              help="额外展示重复流水：银行自身重复 / mny 自身重复 / 两边都重复")
@click.option("--adjust/--no-adjust", default=False,
              help="提供外部余额时，是否直接生成校准记录（差额用其他收入/支出记账）")
def reconcile_run(account, file, fmt, yes, default_category, balance, show_dupes, adjust):
    """用银行/平台导出的流水和 mny 内记录比对

    CSV/JSON 字段: amount(负数=支出),date(YYYY-MM-DD),note,category,type(income/expense 可选)
    """
    try:
        records = _read_reconcile_file(file, fmt)
    except Exception as e:
        console.print(f"[red]✗[/red] 读取文件失败: {e}")
        return
    if not records:
        console.print("[yellow]文件为空[/yellow]")
        return

    result = models.reconcile_with_balance(records, account, bank_balance=balance)
    matched = result["matched"]
    missing = result["missing_in_mny"]
    extra = result["missing_in_bank"]
    mismatched = result["amount_mismatch"]

    header_lines = [
        f"对账账户: [bold]{result['account']}[/bold]  当前 mny 余额: {_fmt_money(result['account_balance'])}",
        f"已匹配: [green]{matched}[/green]   "
        f"银行有 mny 缺: [yellow]{len(missing)}[/yellow]   "
        f"mny 有银行缺: [cyan]{len(extra)}[/cyan]   "
        f"金额不一致: [red]{len(mismatched)}[/red]",
    ]
    if balance is not None:
        diff = result.get("diff", 0.0)
        diff_str = _fmt_amount(abs(diff), "income" if diff >= 0 else "expense")
        if abs(diff) < 0.005:
            header_lines.append(f"外部余额: {_fmt_money(balance)}  [green]✓ 余额一致[/green]")
        else:
            header_lines.append(
                f"外部余额: {_fmt_money(balance)}  差额: [yellow]{diff_str}[/yellow] "
                f"（mny {'少记' if diff > 0 else '多记'} {_fmt_money(abs(diff))}）"
            )
    console.print(Panel("\n".join(header_lines), title="🔍 对账结果", border_style="cyan"))

    if balance is not None and abs(result.get("diff", 0.0)) >= 0.005:
        if adjust:
            try:
                tx_id = models.create_balance_adjustment(account, balance, tx_date=date.today().isoformat())
                console.print(
                    f"[green]✓[/green] 已生成校准记录 #{tx_id}，"
                    f"mny 余额已对齐至 {_fmt_money(balance)}"
                )
            except Exception as e:
                console.print(f"[red]✗[/red] 校准失败: {e}")
        else:
            diff = result["diff"]
            suggestion = f"其他收入 +{diff:.2f}" if diff > 0 else f"其他支出 {diff:.2f}"
            console.print(
                f"💡 修正方案：生成一条 [yellow]{suggestion}[/yellow] 的校准记录。"
                f" 可加 [cyan]--adjust[/cyan] 直接生成，或手动 `mny add expense/income ...`。"
            )

    if missing:
        table = Table(title=f"❌ mny 中缺失的 {len(missing)} 条银行流水")
        table.add_column("#", justify="right", style="cyan")
        table.add_column("日期", style="magenta")
        table.add_column("类型", justify="center")
        table.add_column("金额", justify="right")
        table.add_column("分类", style="yellow")
        table.add_column("备注")
        for idx, m in enumerate(missing, 1):
            ttype = "[green]收入[/green]" if m["type"] == "income" else "[red]支出[/red]"
            table.add_row(str(idx), m["date"], ttype, _fmt_amount(m["amount"], m["type"]),
                          m.get("category") or "-", m.get("note") or "")
        console.print(table)

        if yes:
            for rec in missing:
                rec["account"] = account
            added, skipped, errors = models.apply_reconcile(missing, default_category)
            console.print(f"[green]✓[/green] 已批量补记 {added} 条" + (f"，跳过 {skipped} 条" if skipped else ""))
            if errors:
                for err in errors:
                    console.print(f"  [yellow]- {err}[/yellow]")
        else:
            answer = Prompt.ask(
                f"选择要补记的编号（1-{len(missing)}，逗号分隔，支持区间如 1-3,5，或 'all' 全部，空=跳过全部）",
                default="", show_default=False,
            ).strip().lower()
            if answer in ("all", "a"):
                selected = list(range(len(missing)))
            elif not answer:
                selected = []
            else:
                selected = []
                for part in answer.split(","):
                    part = part.strip()
                    if "-" in part:
                        try:
                            a, b = part.split("-", 1)
                            selected.extend(range(int(a) - 1, int(b)))
                        except ValueError:
                            pass
                    else:
                        try:
                            selected.append(int(part) - 1)
                        except ValueError:
                            pass
                selected = sorted({i for i in selected if 0 <= i < len(missing)})

            if not selected:
                console.print("[dim]已跳过全部缺失记录[/dim]")
            else:
                chosen = [missing[i] for i in selected]
                for rec in chosen:
                    rec["account"] = account
                added, skipped, errors = models.apply_reconcile(chosen, default_category)
                console.print(f"[green]✓[/green] 已补记 {added} 条（选了 {len(chosen)} 条）" + (f"，跳过 {skipped} 条" if skipped else ""))
                if errors:
                    for err in errors:
                        console.print(f"  [yellow]- {err}[/yellow]")

    if extra:
        table = Table(title=f"⚠ mny 有但银行没出现的 {len(extra)} 条（可能是漏记、重复或日期不一致）")
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("日期", style="magenta")
        table.add_column("类型", justify="center")
        table.add_column("金额", justify="right")
        table.add_column("分类", style="yellow")
        table.add_column("备注")
        for e in extra:
            ttype = "[green]收入[/green]" if e["type"] == "income" else "[red]支出[/red]"
            table.add_row(str(e["id"]), e["date"], ttype, _fmt_amount(e["amount"], e["type"]),
                          e.get("category") or "-", e.get("note") or "")
        console.print(table)

    if mismatched:
        table = Table(title=f"🔴 金额不一致的 {len(mismatched)} 条")
        table.add_column("mny ID", style="cyan", justify="right")
        table.add_column("日期", style="magenta")
        table.add_column("mny 金额", justify="right")
        table.add_column("银行金额", justify="right", style="red")
        table.add_column("备注")
        for mm in mismatched:
            m = mm["mny"]
            table.add_row(str(m["id"]), m["date"],
                          _fmt_amount(mm["mny_amount"], m["type"]),
                          _fmt_amount(mm["bank_amount"], m["type"]),
                          m.get("note") or "")
        console.print(table)

    if show_dupes:
        dup_result = models.find_duplicate_transactions_exclusive(records, account)
        dup_bank = dup_result["duplicates_in_bank"]
        dup_mny = dup_result["duplicates_in_mny"]
        dup_both = dup_result["duplicates_both"]

        if dup_bank:
            table = Table(title=f"🔁 银行流水自身重复 {len(dup_bank)} 组（按 类型|日期|金额|备注 聚合）")
            table.add_column("聚合 Key", overflow="fold")
            table.add_column("重复次数", justify="right")
            table.add_column("建议")
            for d in dup_bank:
                table.add_row(d["key"], str(d["count"]), "[yellow]忽略多余记录[/yellow]")
            console.print(table)

        if dup_mny:
            table = Table(title=f"🔁 mny 自身重复 {len(dup_mny)} 组（按 类型|日期|金额|备注 聚合）")
            table.add_column("聚合 Key", overflow="fold")
            table.add_column("mny 重复次数", justify="right")
            table.add_column("涉及 ID", overflow="fold")
            table.add_column("操作")
            for d in dup_mny:
                ids = ", ".join(str(i["id"]) for i in d["items"])
                table.add_row(d["key"], str(d["count"]), ids, "[cyan]建议只保留1条，其余删除[/cyan]")
            console.print(table)
            if dup_mny and Confirm.ask(
                "是否删除 mny 中每组重复记录多余的条目（只保留最早的 1 条）？", default=False
            ):
                removed = 0
                for d in dup_mny:
                    items = sorted(d["items"], key=lambda x: x["id"])
                    for extra_item in items[1:]:
                        if models.delete_duplicate_mny_transaction(extra_item["id"]):
                            removed += 1
                console.print(f"[green]✓[/green] 删除了 {removed} 条重复交易")

        if dup_both:
            table = Table(title=f"🔁 两边都重复 {len(dup_both)} 组")
            table.add_column("聚合 Key", overflow="fold")
            table.add_column("银行重复", justify="right")
            table.add_column("mny 重复", justify="right")
            table.add_column("mny 涉及 ID", overflow="fold")
            for d in dup_both:
                ids = ", ".join(str(i["id"]) for i in d["mny_items"])
                table.add_row(d["key"], str(d["bank_count"]), str(d["mny_count"]), ids)
            console.print(table)
            if dup_both and Confirm.ask(
                "是否把 mny 每组多余的重复条目也清理掉？", default=False
            ):
                removed = 0
                for d in dup_both:
                    items = sorted(d["mny_items"], key=lambda x: x["id"])
                    for extra_item in items[1:]:
                        if models.delete_duplicate_mny_transaction(extra_item["id"]):
                            removed += 1
                console.print(f"[green]✓[/green] 删除了 {removed} 条重复交易")


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
        if not Confirm.ask(
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
@click.option("--project", default=None)
def export_transactions(output, start, end, tx_type, account, category, keyword, tag, project):
    """导出交易流水"""
    txs = models.list_transactions(start, end, tx_type, account, category, keyword, tag, project)
    if not txs:
        console.print("[yellow]无数据可导出[/yellow]")
        return
    if output.lower().endswith(".json"):
        models.export_transactions_json(output, txs)
    else:
        models.export_transactions_csv(output, txs)
    console.print(f"[green]✓[/green] 已导出 {len(txs)} 条到 {output}")


# ============================================================
# account / category / project / info
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


@cli.group()
def project():
    """管理项目"""
    pass


@project.command("list")
def project_list():
    """列出所有项目"""
    projs = models.list_projects()
    if not projs:
        console.print("[yellow]暂无项目[/yellow]")
        return
    table = Table(title="项目列表")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("名称", style="cyan")
    table.add_column("描述", style="dim")
    for p in projs:
        table.add_row(str(p["id"]), p["name"], p.get("description") or "")
    console.print(table)


@project.command("add")
@click.argument("name")
@click.option("-d", "--description", default=None, help="项目描述")
def project_add(name, description):
    """新增项目"""
    models.add_project(name, description)
    console.print(f"[green]✓[/green] 已添加项目: {name}")


# ============================================================
# snapshot: 净资产快照
# ============================================================
@cli.group()
def snapshot():
    """资产快照：记录某天账户余额、负债，查看净资产趋势"""
    pass


@snapshot.command("record")
@click.option("-d", "--date", "date_str", default=None, help="日期 (YYYY-MM-DD)，默认今天")
@click.option("-a", "--account", default=None,
              help="账户名，为空则记录整体净资产快照")
@click.option("-b", "--balance", type=float, required=True, help="账户余额或总资产")
@click.option("-l", "--liability", type=float, default=0.0, help="负债金额")
@click.option("-n", "--note", default=None, help="备注")
def snapshot_record(date_str, account, balance, liability, note):
    """记录某一天某个账户或整体的资产快照"""
    if date_str is None:
        date_str = date.today().isoformat()
    try:
        sid = models.add_snapshot(date_str, account, balance, liability, note)
        who = account if account else "整体"
        console.print(f"[green]✓[/green] 已记录 {who} 快照 #{sid}: "
                      f"资产 {_fmt_money(balance)} / 负债 {_fmt_money(liability)}")
    except Exception as e:
        console.print(f"[red]✗[/red] {e}")


@snapshot.command("list")
@click.option("-n", "--months", type=int, default=6, show_default=True, help="最近 N 个月")
@click.option("-a", "--account", default=None, help="只看某账户的快照")
def snapshot_list(months, account):
    """列出最近几个月的资产快照"""
    snaps = models.list_snapshots(months, account)
    if not snaps:
        console.print(f"[yellow]最近 {months} 个月没有快照记录[/yellow]")
        return
    table = Table(title=f"📸 最近 {months} 个月资产快照（共 {len(snaps)} 条）")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("日期", style="magenta")
    table.add_column("账户", style="blue")
    table.add_column("余额/资产", justify="right")
    table.add_column("负债", justify="right", style="red")
    table.add_column("净")
    table.add_column("备注")
    for s in snaps:
        who = s["account_name"] or "整体"
        net = s["balance"] - s["liability"]
        table.add_row(
            str(s["id"]), s["date"], who,
            _fmt_money(s["balance"]),
            _fmt_money(s["liability"]) if s["liability"] else "-",
            _fmt_money(net),
            s.get("note") or "",
        )
    console.print(table)


# ============================================================
# report yoy: 年度同比
# ============================================================
@report.command("yoy")
@click.option("-y", "--year", type=int, default=None, help="年份，默认今年")
@click.option("-o", "--output", default=None, help="导出 CSV/JSON")
def report_yoy(year, output):
    """年度同比：今年每月 vs 去年同月 + 分类结构变化"""
    data = models.get_yearly_yoy(year)
    y = data["year"]
    py = data["prev_year"]

    # 月度同比表
    table = Table(title=f"📊 {y} vs {py} 月度同比")
    table.add_column("月份", justify="center", style="cyan")
    for col in ("收入", "支出", "净结余"):
        table.add_column(f"{y} {col}", justify="right")
        table.add_column(f"{py} {col}", justify="right", style="dim")
        table.add_column("增减", justify="right")
        table.add_column("同比", justify="right")
    for m in data["months"]:
        def _fmt_yoy(row, key):
            delta_key = key + "_delta"
            yoy_key = key + "_yoy"
            delta = row[delta_key]
            yoy = row[yoy_key]
            if delta is None or abs(delta) < 0.005:
                return "-", "-"
            s = _fmt_amount(delta, "income" if delta > 0 else "expense")
            if yoy is None:
                return s, "-"
            if yoy > 0:
                return s, f"[green]+{yoy:.1f}%[/green]"
            return s, f"[red]{yoy:.1f}%[/red]"
        inc_d, inc_y = _fmt_yoy(m, "income")
        exp_d, exp_y = _fmt_yoy(m, "expense")
        net_d, net_y = _fmt_yoy(m, "net")
        table.add_row(
            f"{m['month']}月",
            _fmt_money(m["income"]), _fmt_money(m["income_prev"]), inc_d, inc_y,
            _fmt_amount(m["expense"], "expense"), _fmt_amount(m["expense_prev"], "expense"), exp_d, exp_y,
            _fmt_money(m["net"]), _fmt_money(m["net_prev"]), net_d, net_y,
        )
    console.print(table)

    # 分类结构变化
    cats = data["category_changes"]
    if cats:
        table2 = Table(title=f"📊 {y} vs {py} 分类结构变化（按占比差排序）")
        table2.add_column("分类", style="cyan")
        table2.add_column("类型", justify="center")
        table2.add_column(f"{y} 金额", justify="right")
        table2.add_column(f"{py} 金额", justify="right", style="dim")
        table2.add_column("增减", justify="right")
        table2.add_column(f"{y} 占比", justify="right")
        table2.add_column(f"{py} 占比", justify="right", style="dim")
        table2.add_column("占比差", justify="right")
        for c in cats[:30]:
            delta = c["delta"]
            delta_s = _fmt_amount(abs(delta), "income" if delta > 0 else "expense") if abs(delta) > 0.005 else "-"
            share_delta = c["share_delta"]
            if abs(share_delta) > 0.5:
                share_s = f"[green]+{share_delta:+.1f}%[/green]" if share_delta > 0 else f"[red]{share_delta:+.1f}%[/red]"
            else:
                share_s = f"{share_delta:+.1f}%"
            table2.add_row(
                c["name"],
                "[green]收入[/green]" if c["type"] == "income" else "[red]支出[/red]",
                _fmt_money(c["total"]) if c["total"] > 0 else "-",
                _fmt_money(c["total_prev"]) if c["total_prev"] > 0 else "-",
                delta_s,
                f"{c['share']:.1f}%" if c["share"] > 0 else "-",
                f"{c['share_prev']:.1f}%" if c["share_prev"] > 0 else "-",
                share_s,
            )
        console.print(table2)

    if output:
        if output.lower().endswith(".json"):
            models.export_report_json(output, data)
        else:
            month_fields = [
                "row_type", "month", "category", "type",
                "income", "income_prev", "income_delta", "income_yoy",
                "expense", "expense_prev", "expense_delta", "expense_yoy",
                "net", "net_prev", "net_delta", "net_yoy",
                "total", "total_prev", "delta", "share", "share_prev", "share_delta",
            ]
            rows = []
            for m in data["months"]:
                rows.append({
                    "row_type": "month",
                    "month": m["month"], "category": "", "type": "",
                    "income": round(m["income"], 2),
                    "income_prev": round(m["income_prev"], 2),
                    "income_delta": round(m["income_delta"], 2),
                    "income_yoy": round(m["income_yoy"], 2) if m["income_yoy"] is not None else "",
                    "expense": round(m["expense"], 2),
                    "expense_prev": round(m["expense_prev"], 2),
                    "expense_delta": round(m["expense_delta"], 2),
                    "expense_yoy": round(m["expense_yoy"], 2) if m["expense_yoy"] is not None else "",
                    "net": round(m["net"], 2),
                    "net_prev": round(m["net_prev"], 2),
                    "net_delta": round(m["net_delta"], 2),
                    "net_yoy": round(m["net_yoy"], 2) if m["net_yoy"] is not None else "",
                    "total": "", "total_prev": "", "delta": "",
                    "share": "", "share_prev": "", "share_delta": "",
                })
            for c in data["category_changes"]:
                rows.append({
                    "row_type": "category",
                    "month": "", "category": c["name"], "type": c["type"],
                    "income": "", "income_prev": "", "income_delta": "", "income_yoy": "",
                    "expense": "", "expense_prev": "", "expense_delta": "", "expense_yoy": "",
                    "net": "", "net_prev": "", "net_delta": "", "net_yoy": "",
                    "total": round(c["total"], 2),
                    "total_prev": round(c["total_prev"], 2),
                    "delta": round(c["delta"], 2),
                    "share": round(c["share"], 2),
                    "share_prev": round(c["share_prev"], 2),
                    "share_delta": round(c["share_delta"], 2),
                })
            with open(output, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=month_fields)
                writer.writeheader()
                writer.writerows(rows)
        console.print(f"[green]✓[/green] 已导出同比报表到 {output}")


@cli.command("info")
def info():
    """显示工具信息"""
    console.print(Panel(
        f"[bold]mny[/bold] - 命令行记账理财工具 v0.5.0\n\n"
        f"数据库路径: [cyan]{DB_PATH}[/cyan]\n"
        f"使用 '[bold]mny --help[/bold]' 查看全部命令\n"
        f"核心功能: transfer 转账 / recurring 定期记账 / reconcile 对账(含余额校准+编号选择补记) /\n"
        f"          snapshot 净资产快照 / budget 多维度链式滚动预算 / report yoy 年度同比 /\n"
        f"          backup 备份 / export 导出 / trend 趋势视图",
        title="💰 mny",
        border_style="green",
    ))


if __name__ == "__main__":
    cli()
