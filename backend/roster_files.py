import base64
import csv
import io
import posixpath
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile
from access_control import require, BackendError

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def table(fields):
    if fields.get('xlsx'):
        try:
            raw = base64.b64decode(fields['xlsx'], validate=True)
            require(len(raw) <= 2_000_000, 'XLSX должен быть не больше 2 МБ', 400)
            with ZipFile(io.BytesIO(raw)) as archive:
                require(
                    sum(i.file_size for i in archive.infolist()) <= 8_000_000,
                    'Слишком большой распакованный XLSX',
                    400,
                )
                require(len(archive.infolist()) <= 300, 'Слишком сложный XLSX', 400)
                workbook = ET.fromstring(archive.read('xl/workbook.xml'))
                sheet = workbook.find('m:sheets/m:sheet', NS)
                require(sheet is not None, 'В XLSX нет листов', 400)
                relationship = sheet.attrib.get(
                    '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
                )
                links = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
                link = next((r for r in links if r.attrib.get('Id') == relationship), None)
                require(
                    link is not None and link.attrib.get('TargetMode') != 'External',
                    'Лист недоступен',
                    400,
                )
                target = link.attrib['Target']
                path = posixpath.normpath(
                    target.lstrip('/') if target.startswith('/') else 'xl/' + target
                )
                require(
                    path.startswith('xl/') and '..' not in path.split('/'), 'Некорректный лист', 400
                )
                strings = []
                if 'xl/sharedStrings.xml' in archive.namelist():
                    strings = [
                        ''.join(si.itertext())
                        for si in ET.fromstring(archive.read('xl/sharedStrings.xml'))
                    ]
                rows = []
                for row in ET.fromstring(archive.read(path)).findall('m:sheetData/m:row', NS):
                    values = {}
                    for cell in row.findall('m:c', NS):
                        require(
                            cell.find('m:f', NS) is None,
                            'Формулы в списках не поддерживаются: вставьте значения',
                            400,
                        )
                        letters = ''.join(c for c in cell.attrib.get('r', '') if c.isalpha())
                        column = 0
                        for char in letters.upper():
                            column = column * 26 + ord(char) - 64
                        require(1 <= column <= 40, 'В таблице допускается до 40 столбцов', 400)
                        value = cell.findtext('m:v', '', NS)
                        if cell.attrib.get('t') == 's':
                            value = strings[int(value)]
                        elif cell.attrib.get('t') == 'inlineStr':
                            value = ''.join(cell.find('m:is', NS).itertext())
                        values[column - 1] = value
                    if values:
                        rows.append([values.get(i, '') for i in range(max(values) + 1)])
                    require(len(rows) <= 201, 'В одном списке допускается до 200 участников', 400)
                return rows
        except BackendError:
            raise
        except (
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            BadZipFile,
            ET.ParseError,
        ):
            raise BackendError(
                'Не удалось прочитать XLSX. Загрузите обычную книгу Excel без пароля.', 400
            ) from None
    source = fields.get('csv')
    require(
        isinstance(source, str) and 0 < len(source) <= 300_000,
        'CSV должен быть не больше 300 КБ',
        400,
    )
    first = source.lstrip('\ufeff').splitlines()[0] if source.splitlines() else ''
    separator = max((';', ',', '\t'), key=first.count)
    try:
        rows = list(
            csv.reader(io.StringIO(source.lstrip('\ufeff')), delimiter=separator, strict=True)
        )
    except csv.Error:
        raise BackendError('Некорректный CSV: проверьте кавычки', 400) from None
    require(0 < len(rows) <= 201, 'В одном списке допускается до 200 участников', 400)
    return rows


def inspect(fields):
    rows = table(fields)
    require(
        rows and rows[0] and len(set(rows[0])) == len(rows[0]),
        'Нужны уникальные названия столбцов',
        400,
    )
    require(
        'Персональный код' not in rows[0], 'Загрузите исходный список без персональных кодов', 400
    )
    return dict(columns=rows[0], sample=rows[1:6], count=max(0, len(rows) - 1))


def normalized_csv(fields):
    if not fields.get('xlsx') and not fields.get('mapping'):
        return fields.get('csv')
    rows = table(fields)
    require(rows, 'Пустая таблица', 400)
    mapping = fields.get('mapping') or {k: k for k in ('ФИО', 'Роль', 'Класс')}
    require(
        isinstance(mapping, dict) and set(mapping) == {'ФИО', 'Роль', 'Класс'},
        'Сопоставьте три столбца',
        400,
    )
    require(
        all(v in rows[0] for v in mapping.values()) and len(set(mapping.values())) == 3,
        'Выберите три разных столбца',
        400,
    )
    indices = [rows[0].index(mapping[k]) for k in ('ФИО', 'Роль', 'Класс')]
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', lineterminator='\n')
    writer.writerow(['ФИО', 'Роль', 'Класс'])
    for row in rows[1:]:
        writer.writerow([row[i] if i < len(row) else '' for i in indices])
    return output.getvalue()
