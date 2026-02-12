"""
Script de test pour vérifier les modèles Django et la connexion à la base de données.
"""

import os
import django

# Configuration Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blanco.settings')
django.setup()

from core.models import (
    Staff, Client, Supplier,
    Category, Gamme, Rayon, GrammageType, Product, ProductImage,
    Sale, SaleProduct, CreditSale, Refund,
    Supply, Inventory, DailyInventory,
    Exercise, Daily, ExpenseType, RecipeType, DailyExpense, DailyRecipe, ProductExpense
)


def test_connection():
    """Test de connexion à la base de données."""
    print("=" * 60)
    print("TEST DE CONNEXION À LA BASE DE DONNÉES")
    print("=" * 60)
    
    try:
        # Test simple de connexion
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE()")
            db_name = cursor.fetchone()[0]
            print(f"✅ Connecté à la base de données: {db_name}")
        return True
    except Exception as e:
        print(f"❌ Erreur de connexion: {e}")
        return False


def test_models():
    """Test de lecture des données depuis les modèles."""
    print("\n" + "=" * 60)
    print("TEST DES MODÈLES DJANGO")
    print("=" * 60)
    
    models_to_test = [
        ('Staff', Staff),
        ('Client', Client),
        ('Supplier', Supplier),
        ('Category', Category),
        ('Gamme', Gamme),
        ('Rayon', Rayon),
        ('GrammageType', GrammageType),
        ('Product', Product),
        ('ProductImage', ProductImage),
        ('Sale', Sale),
        ('SaleProduct', SaleProduct),
        ('CreditSale', CreditSale),
        ('Refund', Refund),
        ('Supply', Supply),
        ('Inventory', Inventory),
        ('DailyInventory', DailyInventory),
        ('Exercise', Exercise),
        ('Daily', Daily),
        ('ExpenseType', ExpenseType),
        ('RecipeType', RecipeType),
        ('DailyExpense', DailyExpense),
        ('DailyRecipe', DailyRecipe),
        ('ProductExpense', ProductExpense),
    ]
    
    results = []
    
    for model_name, model_class in models_to_test:
        try:
            count = model_class.objects.count()
            print(f"✅ {model_name:20} : {count:6} enregistrements")
            results.append((model_name, count, True))
        except Exception as e:
            print(f"❌ {model_name:20} : Erreur - {str(e)[:50]}")
            results.append((model_name, 0, False))
    
    return results


def test_relationships():
    """Test des relations entre modèles."""
    print("\n" + "=" * 60)
    print("TEST DES RELATIONS")
    print("=" * 60)
    
    try:
        # Test Product -> Category
        products_with_category = Product.objects.filter(category__isnull=False).count()
        print(f"✅ Produits avec catégorie: {products_with_category}")
        
        # Test Sale -> SaleProduct
        sales_with_products = Sale.objects.filter(sale_products__isnull=False).distinct().count()
        print(f"✅ Ventes avec produits: {sales_with_products}")
        
        # Test Daily -> Exercise
        dailies_with_exercise = Daily.objects.filter(exercise__isnull=False).count()
        print(f"✅ Sessions avec exercice: {dailies_with_exercise}")
        
        print("\n✅ Relations fonctionnent correctement!")
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors du test des relations: {e}")
        return False


def display_summary(results):
    """Affiche un résumé des tests."""
    print("\n" + "=" * 60)
    print("RÉSUMÉ DES TESTS")
    print("=" * 60)
    
    total_models = len(results)
    successful_models = sum(1 for _, _, success in results if success)
    total_records = sum(count for _, count, success in results if success)
    
    print(f"Modèles testés: {successful_models}/{total_models}")
    print(f"Total d'enregistrements: {total_records}")
    
    if successful_models == total_models:
        print("\n🎉 TOUS LES TESTS SONT PASSÉS AVEC SUCCÈS!")
    else:
        print(f"\n⚠️  {total_models - successful_models} modèle(s) en erreur")
    
    print("=" * 60)


if __name__ == '__main__':
    if test_connection():
        results = test_models()
        test_relationships()
        display_summary(results)
    else:
        print("\n❌ Impossible de continuer sans connexion à la base de données.")

