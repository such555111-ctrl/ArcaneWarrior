#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_tilda.py — разовый импорт товаров из CSV-выгрузки Tilda в products.json.

Скрипт изолирован от проекта: не импортирует main.py, ничего не меняет,
кроме products.json (создаёт резервную копию перед записью).

Использование:
    python import_tilda.py путь/к/выгрузке.csv [--products путь/к/products.json] [--dry-run]

Логика:
  - Читает CSV (разделитель ';', как в стандартной выгрузке Tilda).
  - Берёт поля Title, Category, Price, Photo, Description (или Text, если
    Description пусто — с очисткой от HTML-тегов), SKU.
  - Цену очищает от пробелов/неразрывных пробелов, запятая -> точка, приводит к int.
  - Категория: берётся первый сегмент до ';' и до первого '>>>' (верхний уровень).
  - Товары со структурой, совместимой с существующим products.json
    (id, name, category, price, old_price, badge, sizes, swatch, desc, images, image, sku).
  - Дубликаты не создаются: сверка идёт по названию товара (name, без учёта
    регистра/пробелов) среди уже существующих записей в products.json —
    повторный запуск скрипта на том же CSV ничего не добавит повторно.
"""

import argparse
import csv
import html
import json
import os
import re
import shutil
import sys
from datetime import datetime


def clean_price(raw):
    """Убирает пробелы/неразрывные пробелы, приводит запятую к точке, возвращает int или None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # убрать обычные и неразрывные пробелы
    s = s.replace("\xa0", "").replace(" ", "")
    if "," in s and "." in s:
        # запятая как разделитель тысяч
        s = s.replace(",", "")
    elif "," in s:
        # запятая как десятичный разделитель
        s = s.replace(",", ".")
    try:
        value = float(s)
    except ValueError:
        return None
    if value <= 0:
        return None
    return int(round(value))


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t]+")
NL_RE = re.compile(r"\n{3,}")


def html_to_text(raw):
    """Грубая, но достаточная очистка HTML-описания Tilda до простого текста."""
    if not raw:
        return ""
    text = raw.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    text = text.replace("</li>", "\n").replace("</p>", "\n")
    text = TAG_RE.sub("", text)
    text = html.unescape(text)
    text = WS_RE.sub(" ", text)
    text = NL_RE.sub("\n\n", text)
    return text.strip()


def clean_category(raw):
    if not raw:
        return ""
    first_segment = raw.split(";")[0].strip()
    top_level = first_segment.split(">>>")[0].strip()
    return top_level


def normalize_name(name):
    return " ".join(name.strip().lower().split())


def load_products(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_products(path, items):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def read_csv_rows(path):
    # Tilda обычно отдаёт UTF-8 с BOM
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(f, delimiter=delimiter)
        return list(reader)


def main():
    parser = argparse.ArgumentParser(description="Импорт товаров из CSV Tilda в products.json")
    parser.add_argument("csv_path", help="Путь к CSV-файлу выгрузки из Tilda")
    parser.add_argument(
        "--products",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "products.json"),
        help="Путь к products.json (по умолчанию рядом со скриптом)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать, что будет добавлено, без записи в products.json",
    )
    args = parser.parse_args()

    if not os.path.exists(args.csv_path):
        print(f"Файл не найден: {args.csv_path}")
        sys.exit(1)

    rows = read_csv_rows(args.csv_path)
    print(f"Прочитано строк в CSV: {len(rows)}")

    existing = load_products(args.products)
    existing_names = {normalize_name(p.get("name", "")) for p in existing}
    next_id = (max([p.get("id", 0) for p in existing], default=0) + 1)

    added = []
    skipped_duplicate = 0
    skipped_no_title = 0
    skipped_bad_price = 0

    for row in rows:
        title = (row.get("Title") or "").strip()
        if not title:
            skipped_no_title += 1
            continue

        key = normalize_name(title)
        if key in existing_names:
            skipped_duplicate += 1
            continue

        price = clean_price(row.get("Price"))
        if price is None:
            skipped_bad_price += 1
            continue

        old_price = clean_price(row.get("Price Old"))
        if old_price is not None and old_price <= price:
            old_price = None

        category = clean_category(row.get("Category"))

        photo = (row.get("Photo") or "").strip()
        images = [photo] if photo else []

        desc = (row.get("Description") or "").strip()
        if not desc:
            desc = html_to_text(row.get("Text") or "")

        sku = (row.get("SKU") or "").strip() or None

        product = {
            "id": next_id,
            "name": title,
            "category": category,
            "price": price,
            "old_price": old_price,
            "badge": None,
            "sizes": ["One size"],
            "swatch": next_id % 6,
            "desc": desc,
            "images": images,
            "image": images[0] if images else None,
            "sku": sku,
        }

        added.append(product)
        existing_names.add(key)
        next_id += 1

    print(f"Будет добавлено новых товаров: {len(added)}")
    print(f"Пропущено (уже есть по названию): {skipped_duplicate}")
    print(f"Пропущено (нет цены/цена <= 0): {skipped_bad_price}")
    if skipped_no_title:
        print(f"Пропущено (нет названия): {skipped_no_title}")

    if args.dry_run:
        print("\n--dry-run: запись в products.json не выполнена.")
        return

    if not added:
        print("Нечего добавлять — products.json не изменён.")
        return

    if os.path.exists(args.products):
        backup_path = args.products + f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        shutil.copy2(args.products, backup_path)
        print(f"Резервная копия сохранена: {backup_path}")

    updated = existing + added
    save_products(args.products, updated)
    print(f"Готово. products.json обновлён, всего товаров: {len(updated)}")


if __name__ == "__main__":
    main()
