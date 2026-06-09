import csv
import json
from datetime import date, datetime
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

from .db import init_db, DB_PATH
from . import models

console = Console()


def _fmt_amount(amount: float, tx_type: Optional[str] = None) -> str:
    if tx_type == "income" or (tx_type is None and amount >= 0):
        return f"[green]+¥{abs(amount):,.2f}[/green]"
    return f"[red]-¥{abs(amount):,.2f}[/red]"


def _fmt_money(amount: float) -> str:
    if amount >= 0:
        return f"[green]¥{amount:,.2f}[/green]"
    return f"[red]¥{amount:,.2f}[/red]"


@click.group()
@click.version_option(package_name="mny")
def cli():
    """mny - 命令行记账理财工具"""
    init_db()


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

    AMOUNT: 收入金额
    """
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

    AMOUNT: 支出金额
    """
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    try:
        tx_id = models.add_transaction("expense", amount, account, category, tx_date, note, tag_list)
        console.print(f"[green]✓[/green] 已记录支出 #{tx_id}: {_fmt_amount(amount, 'expense')} | {account} | {category}")
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")


@cli.command("list")
@click.option("--from", "start", default=None, help="起始日期 YYYY-MM-DD")
@click.option("--to", "end", default=None, help="结束日期 YYYY-MM-DD")
@click.option("-t", "--type", "tx_type", default=None, type=click.Choice(["income", "expense"]), help="类型")
@click.option("-a", "--account", default=None, help="账户筛选")
@click.option("-c", "--category", default=None, help="分类筛选")
@click.option("-k", "--keyword", default=None, help="关键词搜索（备注或分类）")
@click.option("--tag", default=None, help="标签筛选")
@click.option("-n", "--limit", default=None, type=int, help="显示条数")
def list_cmd(start, end, tx_type, account, category, keyword, tag, limit):
    """查询交易流水"""
    txs = models.list_transactions(start, end, tx_type, account, category, keyword, tag, limit)
    if not txs:
        console.print("[yellow]没有找到匹配的记录[/yellow]")
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
            str(tx["id"]),
            tx["date"],
            ttype,
            _fmt_amount(tx["amount"], tx["type"]),
            tx["account"],
            tx["category"],
            ", ".join(tx["tags"]),
            tx.get("note") or "",
        )

    console.print(table)
    footer = f"合计: 收入 {_fmt_money(total_income)} | 支出 {_fmt_money(-total_expense)} | 净结余 {_fmt_money(total_income - total_expense)}"
    console.print(Panel(footer, border_style="dim"))


@cli.group()
def edit():
    """修改或删除账目"""
    pass


@edit.command("update")
@click.argument("tx_id", type=int)
@click.option("--type", "tx_type", default=None, type=click.Choice(["income", "expense"]), help="类型")
@click.option("--amount", default=None, type=float, help="金额")
@click.option("-a", "--account", default=None, help="账户")
@click.option("-c", "--category", default=None, help="分类")
@click.option("-d", "--date", "tx_date", default=None, help="日期")
@click.option("-n", "--note", default=None, help="备注")
@click.option("-t", "--tags", default=None, help="标签，逗号分隔（覆盖原标签）")
def edit_update(tx_id, tx_type, amount, account, category, tx_date, note, tags):
    """修改交易记录

    TX_ID: 交易ID
    """
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
    """删除交易记录

    TX_ID: 交易ID
    """
    tx = models.get_transaction(tx_id)
    if not tx:
        console.print(f"[red]✗[/red] 交易不存在: #{tx_id}")
        return
    _print_tx_detail(tx)
    if not yes:
        if not click.confirm("确认删除这条记录？", default=False):
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
    """设置月度预算

    CATEGORY: 支出分类名称
    AMOUNT: 预算金额
    """
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


@cli.group()
def report():
    """生成报表：周报、月报、年报等"""
    pass


@report.command("weekly")
def report_weekly():
    """本周收支概览"""
    data = models.get_weekly_summary()
    console.print(Panel(
        f"报告周期: [bold]{data['start']}[/bold] 至 [bold]{data['end']}[/bold]\n"
        f"收入: {_fmt_money(data['income'])}  支出: {_fmt_money(-data['expense'])}  净结余: {_fmt_money(data['net'])}",
        title="📊 周报表",
        border_style="blue",
    ))
    _print_category_breakdown(data["by_category"])


@report.command("monthly")
@click.option("-y", "--year", type=int, default=None, help="年份，默认今年")
@click.option("-m", "--month", type=int, default=None, help="月份，默认本月")
def report_monthly(year, month):
    """月度收支报表"""
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    data = models.get_monthly_summary(year, month)
    console.print(Panel(
        f"报告周期: [bold]{year}-{month:02d}[/bold]\n"
        f"收入: {_fmt_money(data['income'])}  支出: {_fmt_money(-data['expense'])}  净结余: {_fmt_money(data['net'])}",
        title=f"📊 {year}-{month:02d} 月报表",
        border_style="blue",
    ))
    _print_category_breakdown(data["by_category"])


@report.command("yearly")
@click.option("-y", "--year", type=int, default=None, help="年份，默认今年")
def report_yearly(year):
    """年度收支报表"""
    today = date.today()
    if year is None:
        year = today.year

    data = models.get_yearly_summary(year)
    console.print(Panel(
        f"报告周期: [bold]{year}[/bold] 全年\n"
        f"收入: {_fmt_money(data['income'])}  支出: {_fmt_money(-data['expense'])}  净结余: {_fmt_money(data['net'])}",
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
            _fmt_money(-d["expense"]),
            _fmt_money(net),
        )
    console.print(table)


@report.command("balance")
def report_balance():
    """账户余额概览"""
    accounts = models.get_account_balances()
    if not accounts:
        console.print("[yellow]暂无账户[/yellow]")
        return

    table = Table(title="💰 账户余额概览")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("账户", style="blue")
    table.add_column("类型", style="magenta")
    table.add_column("余额", justify="right")
    table.add_column("累计收入", justify="right")
    table.add_column("累计支出", justify="right")

    total = 0.0
    for acc in accounts:
        total += acc["balance"]
        table.add_row(
            str(acc["id"]),
            acc["name"],
            acc["type"],
            _fmt_money(acc["balance"]),
            _fmt_money(acc["total_income"]),
            _fmt_money(-acc["total_expense"]),
        )

    console.print(table)
    console.print(f"\n[bold]总资产:[/bold] {_fmt_money(total)}")


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
            table.add_row(c["category"], _fmt_money(c["total"]), f"{pct:.1f}%", f"[green]{bar}[/green]")
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
            table.add_row(c["category"], _fmt_money(-c["total"]), f"{pct:.1f}%", f"[red]{bar}[/red]")
        console.print(table)


@cli.command("import")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("-f", "--format", "fmt", default="csv", type=click.Choice(["csv", "json"]), show_default=True, help="文件格式")
def import_cmd(file, fmt):
    """导入账单文件（CSV或JSON），自动合并重复

    FILE: 账单文件路径

    CSV字段: type(income/expense),amount,account,category,date(YYYY-MM-DD),note,tags(逗号分隔)
    """
    try:
        records = []
        if fmt == "csv":
            with open(file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append(_parse_csv_row(row))
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

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task(f"正在导入 {len(records)} 条记录...", total=None)
            added, skipped = models.bulk_import(records)

        console.print(f"[green]✓[/green] 导入完成: 新增 {added} 条，跳过重复/无效 {skipped} 条")
    except Exception as e:
        console.print(f"[red]✗[/red] 导入失败: {e}")


def _parse_csv_row(row):
    tx_type = row.get("type", "").strip().lower()
    if tx_type not in ("income", "expense"):
        raise ValueError(f"无效的交易类型: {tx_type}")
    amount = float(row.get("amount", 0))
    account = row.get("account", "现金").strip()
    category = row.get("category", "其他收入" if tx_type == "income" else "其他支出").strip()
    tx_date = row.get("date", date.today().isoformat()).strip()
    note = row.get("note", "").strip() or None
    tags_str = row.get("tags", "").strip()
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
    return {
        "type": tx_type,
        "amount": amount,
        "account": account,
        "category": category,
        "date": tx_date,
        "note": note,
        "tags": tags,
    }


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
    console.print(f"[green]✓[/green] 已添加账户: {name} (¥{balance:,.2f})")


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
        f"[bold]mny[/bold] - 命令行记账理财工具 v0.1.0\n\n"
        f"数据库路径: [cyan]{DB_PATH}[/cyan]\n"
        f"使用 '[bold]mny --help[/bold]' 查看全部命令",
        title="💰 mny",
        border_style="green",
    ))


if __name__ == "__main__":
    cli()
