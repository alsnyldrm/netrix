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
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from .csv_transfer import (
    ENUMS,
    FIELDS,
    MAX_BYTES,
    MAX_ROWS,
    REFERENCES,
    REQUIRED,
    SECRETS,
    TEMPLATE_FIELDS,
    safe_cell,
)
from .template_choices import MAX_CHOICES

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def add_choice_lists(book, sheet, choices):
    lists = book.create_sheet("Seçenekler")
    lists.sheet_state = "hidden"
    for column, key in enumerate((*TEMPLATE_FIELDS, *SECRETS), 1):
        letter = get_column_letter(column)
        # Every input column offers suggestions, without preventing new free text.
        values = choices.get(key, ["********"] if key in SECRETS else [])
        lists.cell(1, column, (FIELDS | SECRETS)[key]).font = Font(name="Arial", size=11)
        for row, value in enumerate(values, 2):
            cell = lists.cell(row, column, safe_cell(value))
            cell.data_type = "s"
            cell.font = Font(name="Arial", size=11)
        name = "netrix_" + key
        book.defined_names.add(
            DefinedName(name, attr_text=f"'Seçenekler'!${letter}$2:${letter}${max(2, len(values) + 1)}")
        )
        strict = key in REFERENCES or key in ENUMS or key in SECRETS or key in ("ssh_trust_host_key",)
        validation = DataValidation(
            type="list",
            formula1="=" + name,
            allow_blank=key not in REQUIRED,
            showDropDown=False,
            showErrorMessage=strict,
            showInputMessage=True,
            errorStyle="stop",
        )
        validation.errorTitle = "Geçersiz seçim"
        validation.error = "Listeden seçim yapın. Yeni kayıt eklendiyse güncel şablonu indirin."
        validation.promptTitle = "Zorunlu alan" if key in REQUIRED else "İsteğe bağlı alan"
        validation.prompt = (
            "Hücrenin yanındaki oktan seçim yapın. Liste şablon indirilirken güncellenir."
            if values and strict
            else "Listede kayıt yok. Önce NETRIX'te ilgili kaydı oluşturup şablonu yeniden indirin."
            if strict
            else "Mevcut değerlerden seçebilir veya yeni bir değer yazabilirsiniz."
        )
        sheet.add_data_validation(validation)
        validation.add(f"{letter}2:{letter}{MAX_ROWS + 1}")


def from_csv(content, *, is_template=False, choices=None):
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
        fields = TEMPLATE_FIELDS if is_template else FIELDS
        for col, (key, label) in enumerate({**fields, **SECRETS}.items(), 1):
            cell = sheet.cell(1, col)
            cell.fill = PatternFill("solid", fgColor="1D4ED8" if key in REQUIRED else "334155")
            cell.font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
            cell.comment = Comment(
                "Zorunlu alan" if key in REQUIRED else "İsteğe bağlı; boş bırakılabilir", "NETRIX"
            )
            sheet.column_dimensions[get_column_letter(col)].width = min(38, max(22, len(label) + 3))
            sheet.column_dimensions[get_column_letter(col)].font = Font(name="Arial", size=11)
        sheet.row_dimensions[1].height = 36
        sheet.freeze_panes = "A2"
        if not is_template:
            sheet.auto_filter.ref = sheet.dimensions
        if is_template:
            guide = book.create_sheet("Açıklamalar")
            for line in (
                "Cihazlar sayfasındaki örnek satırı kendi cihazınızın bilgileriyle değiştirin; her yeni cihaz için bir satır ekleyin.",
                "* işaretli ilk sekiz sütun zorunludur: Cihaz adı, Yönetim IP adresi, SNMP profili, SSH / API profili, Anahtara güven, Lokasyon, Yaşam döngüsü, Konfigürasyon adaptörü. Diğer sütunlar isteğe bağlıdır.",
                "192.0.2.10 örnek adrestir. VRF boş bırakılırsa Global kullanılır; farklı VRF için listeden seçim yapın. Global bulunamazsa içeri aktarma hata verir.",
                "2. satırdan itibaren hücreyi seçip yanındaki oka basın. 500 cihaz satırında açılır liste vardır. Listeler şablon indirme anındaki kayıtları içerir; yeni kayıtlar için şablonu yeniden indirin.",
                "SNMP profili yalnızca SNMPv2c/v3, SSH / API profili yalnızca SSH/API kayıtlarını listeler. API profili için rest adaptörünü seçin. Aynı ada sahip kayıtlar kimlikleriyle gösterilir.",
                "Cihaz adı, IP ve diğer serbest alanlarda mevcut önerilerden seçebilir veya yeni değer yazabilirsiniz. Liste boşsa ilgili profil/lokasyonu NETRIX'te oluşturun. Örnek satırdaki seçimleri kendi cihazınıza göre değiştirin.",
                "Anahtara güven: Evet veya Hayır girin; boş bırakılamaz. Örnek Hayır değeri SSH host anahtarı doğrulamasını korur.",
                "Parola, token, community ve anahtar sütunlarını boş veya yıldızlı bırakın. Formül kullanmayın.",
                "İçeri Aktar ve Test Et: atanmış profiller yetkili ağ kapsamlarında test edilir. Kapsam uygun değilse test edilemedi olarak gösterilir.",
                "En fazla 500 cihaz / 1 MiB. Mevcut cihazlar güncellenmez; hatalı satır varsa dosyanın tamamı reddedilir.",
            ):
                guide.append([line])
                cell = guide.cell(guide.max_row, 1)
                cell.font = Font(name="Arial", size=11)
                cell.alignment = Alignment(wrap_text=True, vertical="center")
                guide.row_dimensions[guide.max_row].height = 48
            guide.column_dimensions["A"].width = 110
            add_choice_lists(book, sheet, choices or {})
        output = io.BytesIO()
        book.save(output)
        if is_template:
            with ZipFile(io.BytesIO(output.getvalue())) as archive:
                if (
                    len(output.getvalue()) > MAX_BYTES
                    or sum(entry.file_size for entry in archive.infolist()) > 8 * MAX_BYTES
                ):
                    raise HTTPException(
                        422, "Excel seçim listeleri dosya sınırını aşıyor; CSV şablonunu kullanın"
                    )
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
                                    or row > MAX_CHOICES + 1
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
