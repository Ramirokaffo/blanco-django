"""
Service de migration des données de l'ancien système.
Parse les données SQL VALUES et les importe dans le nouveau système Django.
"""

import re
from django.db import transaction
from core.models.product_models import (
    Product, ProductImage, Category, Gamme, Rayon, GrammageType
)


def parse_sql_values(raw_text):
    """
    Parse une chaîne SQL VALUES de la forme :
    (val1, val2, ...),(val1, val2, ...),...
    Retourne une liste de listes de valeurs Python (str, int, float, None).
    """
    if not raw_text or not raw_text.strip():
        return []

    text = raw_text.strip()
    # Supprimer un éventuel point-virgule final
    if text.endswith(';'):
        text = text[:-1].strip()

    rows = []
    i = 0
    length = len(text)

    while i < length:
        # Chercher le début d'un tuple
        while i < length and text[i] != '(':
            i += 1
        if i >= length:
            break
        i += 1  # Skip '('

        values = []
        while i < length and text[i] != ')':
            # Skip whitespace
            while i < length and text[i] in (' ', '\t'):
                i += 1

            if i >= length or text[i] == ')':
                break

            if text[i] == ',':
                i += 1
                continue

            if text[i] == "'":
                # Parse string value
                i += 1
                val_chars = []
                while i < length:
                    if text[i] == '\\' and i + 1 < length:
                        val_chars.append(text[i + 1])
                        i += 2
                    elif text[i] == "'" and i + 1 < length and text[i + 1] == "'":
                        val_chars.append("'")
                        i += 2
                    elif text[i] == "'":
                        i += 1
                        break
                    else:
                        val_chars.append(text[i])
                        i += 1
                values.append(''.join(val_chars))
            elif text[i:i+4].upper() == 'NULL':
                values.append(None)
                i += 4
            else:
                # Parse numeric value
                val_chars = []
                while i < length and text[i] not in (',', ')'):
                    val_chars.append(text[i])
                    i += 1
                val_str = ''.join(val_chars).strip()
                if val_str:
                    try:
                        if '.' in val_str:
                            values.append(float(val_str))
                        else:
                            values.append(int(val_str))
                    except ValueError:
                        values.append(val_str)

        if i < length and text[i] == ')':
            i += 1

        if values:
            rows.append(values)

    return rows


def _parse_simple_table(raw_text):
    """Parse une table simple (category, gamme, rayon, grammage_type).
    Colonnes attendues : id, name, description, create_at, delete_at
    Retourne dict {old_id: {'name': ..., 'description': ...}}
    """
    rows = parse_sql_values(raw_text)
    result = {}
    for row in rows:
        if len(row) >= 2:
            old_id = row[0]
            name = row[1]
            description = row[2] if len(row) > 2 else None
            result[old_id] = {'name': name or '', 'description': description}
    return result


def migrate_data(
    products_sql='',
    images_sql='',
    categories_sql='',
    gammes_sql='',
    rayons_sql='',
    grammage_types_sql='',
):
    """
    Migre les données de l'ancien système vers le nouveau.
    Retourne un dict avec les statistiques de migration.
    """
    stats = {
        'categories': 0, 'gammes': 0, 'rayons': 0,
        'grammage_types': 0, 'products': 0, 'images': 0,
        'errors': [],
    }

    # Mappings old_id -> new_id
    cat_map = {}
    gamme_map = {}
    rayon_map = {}
    gt_map = {}
    product_map = {}

    with transaction.atomic():
        # 1. Importer les catégories
        if categories_sql.strip():
            cat_data = _parse_simple_table(categories_sql)
            for old_id, data in cat_data.items():
                obj, created = Category.objects.get_or_create(
                    name=data['name'],
                    defaults={'description': data['description']}
                )
                cat_map[old_id] = obj.id
                if created:
                    stats['categories'] += 1

        # 2. Importer les gammes
        if gammes_sql.strip():
            gamme_data = _parse_simple_table(gammes_sql)
            for old_id, data in gamme_data.items():
                obj, created = Gamme.objects.get_or_create(
                    name=data['name'],
                    defaults={'description': data['description']}
                )
                gamme_map[old_id] = obj.id
                if created:
                    stats['gammes'] += 1

        # 3. Importer les rayons
        if rayons_sql.strip():
            rayon_data = _parse_simple_table(rayons_sql)
            for old_id, data in rayon_data.items():
                obj, created = Rayon.objects.get_or_create(
                    name=data['name'],
                    defaults={'description': data['description']}
                )
                rayon_map[old_id] = obj.id
                if created:
                    stats['rayons'] += 1

        # 4. Importer les types de grammage
        if grammage_types_sql.strip():
            gt_data = _parse_simple_table(grammage_types_sql)
            for old_id, data in gt_data.items():
                obj, created = GrammageType.objects.get_or_create(
                    name=data['name'],
                    defaults={'description': data['description']}
                )
                gt_map[old_id] = obj.id
                if created:
                    stats['grammage_types'] += 1

        # 5. Importer les produits
        # Colonnes ancien système :
        # id, code, name, description, brand, color, stock_limit, grammage,
        # exp_alert_period, is_price_reducible, grammage_type_id, gamme_id,
        # category_id, rayon_id, create_at, delete_at, max_salable_price
        if products_sql.strip():
            product_rows = parse_sql_values(products_sql)
            for row in product_rows:
                try:
                    if len(row) < 14:
                        stats['errors'].append(
                            f"Produit ignoré (colonnes insuffisantes) : {row[:3]}"
                        )
                        continue

                    old_id = row[0]
                    code = str(row[1]) if row[1] else ''
                    name = str(row[2]) if row[2] else ''
                    description = str(row[3]) if row[3] else ''
                    brand = str(row[4]) if row[4] else ''
                    color = str(row[5]) if row[5] else None
                    stock_limit = row[6] if isinstance(row[6], int) else None
                    grammage = float(row[7]) if row[7] is not None else None
                    exp_alert_period = row[8] if isinstance(row[8], int) else None
                    is_price_reducible = bool(row[9]) if row[9] is not None else True

                    # Résoudre les FK via les mappings
                    grammage_type_id = gt_map.get(row[10]) if row[10] is not None else None
                    gamme_id = gamme_map.get(row[11]) if row[11] is not None else None
                    category_id = cat_map.get(row[12]) if row[12] is not None else None
                    rayon_id = rayon_map.get(row[13]) if row[13] is not None else None

                    max_salable_price = None
                    if len(row) > 16 and row[16] is not None:
                        try:
                            max_salable_price = float(row[16])
                        except (ValueError, TypeError):
                            pass

                    # Vérifier si le produit existe déjà par code
                    if Product.objects.filter(code=code).exists():
                        existing = Product.objects.get(code=code)
                        product_map[old_id] = existing.id
                        stats['errors'].append(
                            f"Produit '{name}' (code={code}) existe déjà, ignoré."
                        )
                        continue

                    product = Product.objects.create(
                        code=code,
                        name=name,
                        description=description,
                        brand=brand,
                        color=color,
                        stock_limit=stock_limit,
                        grammage=grammage,
                        exp_alert_period=exp_alert_period,
                        is_price_reducible=is_price_reducible,
                        grammage_type_id=grammage_type_id,
                        gamme_id=gamme_id,
                        category_id=category_id,
                        rayon_id=rayon_id,
                        max_salable_price=max_salable_price,
                        stock=0,
                    )
                    product_map[old_id] = product.id
                    stats['products'] += 1

                except Exception as e:
                    stats['errors'].append(
                        f"Erreur produit (row={row[:3]}): {str(e)}"
                    )

        # 6. Importer les images
        # Colonnes ancien système :
        # id, path, description, product_id, create_at, delete_at
        if images_sql.strip():
            image_rows = parse_sql_values(images_sql)
            for row in image_rows:
                try:
                    if len(row) < 4:
                        stats['errors'].append(
                            f"Image ignorée (colonnes insuffisantes) : {row}"
                        )
                        continue

                    image_path = str(row[1]) if row[1] else ''
                    description = str(row[2]) if row[2] else ''
                    old_product_id = row[3]

                    new_product_id = product_map.get(old_product_id)
                    if new_product_id is None:
                        stats['errors'].append(
                            f"Image ignorée (produit ancien ID={old_product_id} non trouvé) : {image_path}"
                        )
                        continue

                    # Vérifier delete_at de l'ancienne image
                    delete_at = row[5] if len(row) > 5 else None
                    if delete_at is not None:
                        continue  # Image supprimée dans l'ancien système

                    ProductImage.objects.create(
                        product_id=new_product_id,
                        image_path=image_path,
                        is_primary=False,
                    )
                    stats['images'] += 1

                except Exception as e:
                    stats['errors'].append(
                        f"Erreur image (row={row[:3]}): {str(e)}"
                    )

    return stats

