"""
产地快打 — Excel 导出工具类

生成双行表头（第一行分类、第二行字段）的导出文件，
数据从第三行开始，业务层只负责传入分类结构与数据行。
"""

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# 导出表头 -> fields dict 字段路径映射；未列出的字段导出时留空
EXPORT_FIELD_MAP = {
    "寄件人姓名": "sender_name",
    "寄件人手机": "sender_phone",
    "寄件人座机": "sender_landline",
    "寄件人地址": "sender_address",
    "寄件人公司": "sender_company",
    "发货仓编码": "sender_warehouse_code",
    "收件人姓名": "name",
    "收件人手机": "phone",
    "收件人座机": "landline",
    "收件人地址": "full_address",
    "收件人公司": "company",
    "物品类型": "items_text",
    "时效产品": "delivery_product",
    "温层": "temperature_layer",
    "面单备注": "notes",
    "自定义信息": "raw",
}


def flatten_categories(categories) -> list:
    """将 [(分类名, [字段...]), ...] 展平为字段标题列表。"""
    return [field for _, fields in categories for field in fields]


def write_export_excel(file_path: str, categories: list, rows: list) -> None:
    """生成双行表头 Excel 文件。

    Args:
        file_path: 保存路径（.xlsx）
        categories: [(分类名, [字段名...]), ...]，仅包含用户勾选的字段
        rows: 数据行，每行顺序与 categories 展平后的字段顺序一致
    """
    headers = flatten_categories(categories)

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "产地快打导出"

    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(
        start_color="D9E1F2", end_color="D9E1F2", fill_type="solid"
    )
    header_alignment = Alignment(horizontal="center", vertical="center")

    col = 1
    for category_name, fields in categories:
        if not fields:
            continue
        start_col = col
        for field in fields:
            cell = ws.cell(row=2, column=col, value=field)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            col += 1
        end_col = col - 1

        cat_cell = ws.cell(row=1, column=start_col, value=category_name)
        cat_cell.font = header_font
        cat_cell.fill = header_fill
        cat_cell.alignment = header_alignment
        if end_col > start_col:
            ws.merge_cells(
                start_row=1, start_column=start_col,
                end_row=1, end_column=end_col,
            )

    for row_idx, row_data in enumerate(rows, 3):
        for col_idx, value in enumerate(row_data, 1):
            ws.cell(row=row_idx, column=col_idx, value=str(value))

    for col_idx, header in enumerate(headers, 1):
        width = max(10, min(30, len(str(header)) * 2 + 4))
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.freeze_panes = "A3"
    wb.save(file_path)
