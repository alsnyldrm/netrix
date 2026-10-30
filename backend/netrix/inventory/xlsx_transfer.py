"""Bounded XLSX transport for the shared device CSV validation pipeline."""

import base64
import csv
import io
from zipfile import ZipFile

from defusedxml.ElementTree import iterparse
from fastapi import HTTPException
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string
from openpyxl.utils.exceptions import IllegalCharacterError

from .csv_transfer import FIELDS, MAX_BYTES, MAX_ROWS, REQUIRED, SECRETS

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def from_csv(content, *, is_template=False):
    book = Workbook()
    sheet = book.active
    sheet.title = "Cihazlar"
    try:
        for row in csv.reader(io.StringIO(content.lstrip("\ufeff"))):
            sheet.append(row)
            for cell in sheet[sheet.max_row]:
                # Always literal text, never a formula or a hyperlink.
                cell.data_type = "s"
                cell.font = Font(name="Arial", size=11)
                cell.alignment = Alignment(vertical="center", wrap_text=True)
        for col, (key, label) in enumerate({**FIELDS, **SECRETS}.items(), 1):
            cell = sheet.cell(1, col)
            cell.fill = PatternFill("solid", fgColor="1D4ED8" if key in REQUIRED else "334155")
            cell.font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
            cell.comment = Comment(
                "Zorunlu alan" if key in REQUIRED else "İsteğe bağlı; boş bırakılabilir", "NETRIX"
            )
            sheet.column_dimensions[get_column_letter(col)].width = min(38, max(22, len(label) + 3))
        sheet.row_dimensions[1].height = 36
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        if is_template:
            guide = book.create_sheet("Açıklamalar")
            for line in (
                "Cihazlar sayfasındaki örnek satırı kendi cihazınızın bilgileriyle değiştirin; her yeni cihaz için bir satır ekleyin.",
                "* işaretli Cihaz adı, Yönetim IP adresi ve VRF zorunludur. Diğer sütunlar isteğe bağlıdır; boş bırakılabilir veya kaldırılabilir.",
                "192.0.2.10 örnek adrestir. Global, mevcut VRF adıdır; kendi VRF adınızı veya kimliğini kullanın.",
                "Lokasyon, yedek grubu ve profiller için kayıtlı ad veya kimlik kullanın. Profilleri önce Erişim kasasında oluşturun.",
                "Parola, token, community ve anahtar sütunlarını boş veya yıldızlı bırakın. Formül kullanmayın.",
                "İçeri Aktar ve Test Et: atanmış profiller yetkili ağ kapsamlarında test edilir. Profil/kapsam eksikse test edilemedi olarak gösterilir.",
                "En fazla 500 cihaz / 1 MiB. Mevcut cihazlar güncellenmez; hatalı satır varsa dosyanın tamamı reddedilir.",
            ):
                guide.append([line])
                cell = guide.cell(guide.max_row, 1)
                cell.font = Font(name="Arial", size=11)
                cell.alignment = Alignment(wrap_text=True, vertical="center")
                guide.row_dimensions[guide.max_row].height = 48
            guide.column_dimensions["A"].width = 110
        output = io.BytesIO()
        book.save(output)
        return output.getvalue()
    except IllegalCharacterError:
        raise HTTPException(422, "Bir cihaz alanı XLSX için geçersiz kontrol karakteri içeriyor") from None
    finally:
        book.close()


def to_csv(encoded):
    book = None
    try:
        data = base64.b64decode(encoded, validate=True)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "XLSX dosyası en fazla 1 MiB olabilir")
        with ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 128 or sum(entry.file_size for entry in entries) > 8 * MAX_BYTES:
                raise HTTPException(422, "XLSX dosyası açılmış boyut sınırını aşıyor")
            if any("vbaproject" in entry.filename.lower() for entry in entries):
                raise HTTPException(422, "Makrolu dosya desteklenmiyor; XLSX şablonunu kullanın")
            for entry in entries:
                if entry.filename.startswith("xl/worksheets/") and entry.filename.endswith(".xml"):
                    with archive.open(entry) as xml:
                        for _, element in iterparse(xml):
                            if element.tag.endswith("}c"):
                                column, row = coordinate_from_string(element.attrib["r"])
                                if (
                                    column_index_from_string(column) > len(FIELDS) + len(SECRETS)
                                    or row > MAX_ROWS + 1
                                ):
                                    raise HTTPException(
                                        422, "XLSX satır veya sütun sınırı aşıldı; şablonu kullanın"
                                    )
                            element.clear()
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
        sheet = book["Cihazlar"] if "Cihazlar" in book.sheetnames else book.active
        # Ignore forged worksheet dimensions; bounded iteration checks actual XML rows.
        sheet.reset_dimensions()
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        width = 0
        for index, row in enumerate(sheet.iter_rows(max_col=len(FIELDS) + len(SECRETS) + 1), 1):
            if index > MAX_ROWS + 1:
                raise HTTPException(422, "Tek dosyada en fazla 500 cihaz içe aktarılabilir")
            values = ["" if cell.value is None else str(cell.value) for cell in row]
            while values and not values[-1]:
                values.pop()
            if len(values) > len(FIELDS) + len(SECRETS) or (index > 1 and len(values) > width):
                raise HTTPException(422, "XLSX sütun sayısı şablon sınırını aşıyor")
            if any(cell.data_type in ("f", "e") for cell in row):
                raise HTTPException(422, f"XLSX satır {index}: formül veya Excel hatası yerine değer girin")
            if index == 1:
                width = len(values)
            writer.writerow(values + [""] * (width - len(values)))
        return output.getvalue()
    except HTTPException:
        raise
    except Exception:
        # Parser diagnostics may contain cell contents: never expose them.
        raise HTTPException(422, "XLSX okunamadı; geçerli XLSX şablonunu kullanın") from None
    finally:
        if book is not None:
            book.close()
