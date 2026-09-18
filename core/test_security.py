"""
Tests de non-régression sécurité (audit de septembre 2026).
"""
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from core.models import (
    Account, AppModule, Client, CreditSupply, Daily, Exercise, JournalEntry,
    Product, Sale, Supplier, Supply, SupplierPayment,
)
from core.services.accounting_service import AccountingService
from core.services.daily_service import DailyService
from core.services.sale_service import SaleService

User = get_user_model()
STATIC_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'


def _grant(user, *codes):
    for code in codes:
        module = AppModule.objects.filter(code=code).first()
        if module:
            user.allowed_modules.add(module)


class SecurityTestBase(TestCase):
    def setUp(self):
        cache.clear()
        AppModule.init_default_modules()
        AccountingService.init_chart_of_accounts()
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@example.com', password='Adm1n-Secure-Pass!',
        )
        self.cashier = User.objects.create_user(
            username='caisse', email='caisse@example.com', password='Caisse-Secure-Pass!',
            firstname='Awa', lastname='Ndongo',
        )
        _grant(self.cashier, 'sales')
        self.product = Product.objects.create(
            code='PRD-SEC', name='Savon', stock=10, actual_price=Decimal('1000'),
            max_salable_price=Decimal('1500'), is_price_reducible=True,
        )

    def token_for(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        return {'HTTP_AUTHORIZATION': f'Token {token.key}'}


@override_settings(STATICFILES_STORAGE=STATIC_STORAGE)
class ImagePathTraversalTests(SecurityTestBase):
    def test_traversal_is_blocked(self):
        for path in ('/api/images/../manage.py/', '/api/images/%2e%2e/manage.py/',
                     '/api/images/../.env/', '/api/images/../db.sqlite3/'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, path)

    def test_only_product_folder_is_served(self):
        from core.services.product_service import ProductService
        self.assertIsNone(ProductService.get_image_path('qrcode', 'qr-server.png'))
        self.assertIsNone(ProductService.get_image_path('product', '..'))
        self.assertIsNone(ProductService.get_image_path('product', 'a/../../.env'))


@override_settings(STATICFILES_STORAGE=STATIC_STORAGE)
class StaffApiPermissionTests(SecurityTestBase):
    def test_signup_creates_inactive_account(self):
        response = self.client.post('/api/staff/', {
            'username': 'nouveau', 'password': 'Un-Mot-De-Passe-Long-42', 'firstname': 'N', 'lastname': 'V',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        user = User.objects.get(username='nouveau')
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_superuser)
        # Le compte ne peut pas encore se connecter à l'API
        login = self.client.post('/api/auth/login/', {
            'username': 'nouveau', 'password': 'Un-Mot-De-Passe-Long-42',
        }, content_type='application/json')
        self.assertEqual(login.status_code, 400)
        self.assertIn('activé', json.dumps(login.json(), ensure_ascii=False))

    def test_signup_requires_password_and_strength(self):
        response = self.client.post('/api/staff/', {'username': 'sansmdp'}, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/staff/', {'username': 'faible', 'password': '123'},
                                    content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_admin_creates_active_account(self):
        response = self.client.post('/api/staff/', {
            'username': 'vendeur2', 'password': 'Un-Mot-De-Passe-Long-42',
        }, content_type='application/json', **self.token_for(self.admin))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(User.objects.get(username='vendeur2').is_active)

    def test_user_cannot_change_another_users_password(self):
        response = self.client.patch(
            f'/api/staff/{self.admin.pk}/update/', {'password': 'Piraté-Mot-De-Passe-99'},
            content_type='application/json', **self.token_for(self.cashier),
        )
        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('Adm1n-Secure-Pass!'))

    def test_user_cannot_change_own_username_or_role(self):
        response = self.client.patch(
            f'/api/staff/{self.cashier.pk}/update/', {'username': 'admin2', 'role': 'Administrateur'},
            content_type='application/json', **self.token_for(self.cashier),
        )
        self.assertEqual(response.status_code, 400)

    def test_own_password_change_requires_current_and_rotates_token(self):
        headers = self.token_for(self.cashier)
        old_key = Token.objects.get(user=self.cashier).key
        response = self.client.patch(
            f'/api/staff/{self.cashier.pk}/update/', {'password': 'Nouveau-Mot-De-Passe-77'},
            content_type='application/json', **headers,
        )
        self.assertEqual(response.status_code, 400)  # current_password manquant
        response = self.client.patch(
            f'/api/staff/{self.cashier.pk}/update/',
            {'password': 'Nouveau-Mot-De-Passe-77', 'current_password': 'Caisse-Secure-Pass!'},
            content_type='application/json', **headers,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn('token', response.json())
        self.assertNotEqual(response.json()['token'], old_key)
        self.assertFalse(Token.objects.filter(key=old_key).exists())

    def test_lookup_by_username_requires_auth(self):
        response = self.client.get('/api/staff/by-username/admin/')
        self.assertEqual(response.status_code, 401)


@override_settings(STATICFILES_STORAGE=STATIC_STORAGE)
class DeactivatedAccountTests(SecurityTestBase):
    def test_soft_deleted_user_cannot_login_and_token_is_revoked(self):
        headers = self.token_for(self.cashier)
        self.assertEqual(self.client.get('/api/products/list/', **headers).status_code, 200)
        self.cashier.delete_at = timezone.now()
        self.cashier.save()
        self.cashier.refresh_from_db()
        self.assertFalse(self.cashier.is_active)
        self.assertFalse(Token.objects.filter(user=self.cashier).exists())
        self.assertEqual(self.client.get('/api/products/list/', **headers).status_code, 401)
        # Login web refusé
        response = self.client.post(reverse('login'), {'username': 'caisse', 'password': 'Caisse-Secure-Pass!'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'incorrect')

    def test_deactivated_user_token_is_revoked(self):
        self.token_for(self.cashier)
        self.cashier.is_active = False
        self.cashier.save()
        self.assertFalse(Token.objects.filter(user=self.cashier).exists())
        self.assertFalse(self.cashier.has_module_access('sales'))


@override_settings(STATICFILES_STORAGE=STATIC_STORAGE)
class ModulePermissionApiTests(SecurityTestBase):
    def test_cashier_cannot_write_products(self):
        response = self.client.patch(
            f'/api/products/{self.product.pk}/update/', {'name': 'X'},
            content_type='application/json', **self.token_for(self.cashier),
        )
        self.assertEqual(response.status_code, 403)

    def test_stock_cannot_be_patched(self):
        _grant(self.cashier, 'products')
        response = self.client.patch(
            f'/api/products/{self.product.pk}/update/', {'stock': 999, 'name': 'Savon doux'},
            content_type='application/json', **self.token_for(self.cashier),
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)
        self.assertEqual(self.product.name, 'Savon doux')

    def test_user_without_module_cannot_sell(self):
        nobody = User.objects.create_user(username='nobody', password='Nobody-Secure-Pass!')
        response = self.client.post('/api/sales/', {
            'items': [{'product_id': self.product.pk, 'quantity': 1, 'unit_price': '1000'}],
        }, content_type='application/json', **self.token_for(nobody))
        self.assertEqual(response.status_code, 403)

    def test_page_params_do_not_crash(self):
        headers = self.token_for(self.cashier)
        self.assertEqual(self.client.get('/api/products/list/?page=abc&count=-5', **headers).status_code, 200)
        self.assertEqual(self.client.get('/api/products/list/?page=-1&count=99999', **headers).status_code, 200)


@override_settings(STATICFILES_STORAGE=STATIC_STORAGE)
class SaleInvariantTests(SecurityTestBase):
    def _sale(self, **item):
        payload = {'items': [{'product_id': self.product.pk, 'quantity': 1, 'unit_price': '1000', **item}]}
        return self.client.post('/api/sales/', payload, content_type='application/json',
                                **self.token_for(self.cashier))

    def test_negative_or_zero_price_rejected(self):
        self.assertEqual(self._sale(unit_price='-1000').status_code, 400)
        self.assertEqual(self._sale(unit_price='0').status_code, 400)
        self.assertEqual(Sale.objects.count(), 0)

    def test_service_enforces_invariants_even_without_serializer(self):
        with self.assertRaises(ValueError):
            SaleService.create_sale({
                'items': [{'product_id': self.product.pk, 'quantity': 1, 'unit_price': Decimal('-5')}],
            }, staff=self.cashier)
        with self.assertRaises(ValueError):
            SaleService.create_sale({
                'items': [{'product_id': self.product.pk, 'quantity': 50, 'unit_price': Decimal('1000')}],
            }, staff=self.cashier)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

    def test_valid_sale_creates_journal_entry(self):
        response = self._sale()
        self.assertEqual(response.status_code, 201, response.content)
        sale = Sale.objects.get()
        self.assertFalse(sale.accounting_pending)
        self.assertTrue(JournalEntry.objects.filter(sale=sale, journal='VE').exists())

    def test_cancel_refused_on_closed_exercise(self):
        self.assertEqual(self._sale().status_code, 201)
        sale = Sale.objects.get()
        exercise = sale.daily.exercise
        exercise.end_date = timezone.now()
        exercise.save(update_fields=['end_date'])
        with self.assertRaises(ValueError):
            SaleService.cancel_sale(sale, reason='test')


@override_settings(STATICFILES_STORAGE=STATIC_STORAGE)
class WebViewHardeningTests(SecurityTestBase):
    def test_login_next_open_redirect_blocked(self):
        response = self.client.post(
            reverse('login') + '?next=https://evil.example/phish',
            {'username': 'admin', 'password': 'Adm1n-Secure-Pass!'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/')

    def test_login_next_local_allowed(self):
        response = self.client.post(
            reverse('login') + '?next=/sales/',
            {'username': 'admin', 'password': 'Adm1n-Secure-Pass!'},
        )
        self.assertEqual(response['Location'], '/sales/')

    @override_settings(LOGIN_RATELIMIT_ATTEMPTS=3)
    def test_login_rate_limited(self):
        for _ in range(3):
            self.client.post(reverse('login'), {'username': 'admin', 'password': 'faux'})
        response = self.client.post(reverse('login'), {'username': 'admin', 'password': 'Adm1n-Secure-Pass!'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Trop de tentatives')

    def test_logout_requires_post(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.assertEqual(self.client.post(reverse('logout')).status_code, 302)

    def test_generate_invoice_requires_post(self):
        self.client.force_login(self.admin)
        response = self.client.post('/api/sales/', {
            'items': [{'product_id': self.product.pk, 'quantity': 1, 'unit_price': '1000'}],
        }, content_type='application/json')
        sale_id = response.json()['sale']['id']
        self.assertEqual(self.client.get(reverse('generate_invoice', args=[sale_id])).status_code, 405)
        self.assertEqual(self.client.post(reverse('generate_invoice', args=[sale_id])).status_code, 302)

    def test_close_daily_requires_open_daily_and_valid_amounts(self):
        self.client.force_login(self.admin)
        url = reverse('close_daily')
        response = self.client.post(url, json.dumps({'cash_in_hand': -5}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        response = self.client.post(url, json.dumps({'cash_in_hand': 'nan'}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Daily.objects.count(), 0)
        DailyService.get_or_create_active_daily()
        response = self.client.post(url, json.dumps({'cash_in_hand': '1000', 'cash_float': '200'}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        # Second appel : plus rien à clôturer, et aucune journée parasite créée
        response = self.client.post(url, json.dumps({'cash_in_hand': '0'}), content_type='application/json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Daily.objects.count(), 1)

    def test_close_daily_needs_sales_module(self):
        viewer = User.objects.create_user(username='viewer', password='Viewer-Secure-Pass!')
        _grant(viewer, 'dashboard')
        self.client.force_login(viewer)
        response = self.client.post(reverse('close_daily'), json.dumps({}), content_type='application/json')
        self.assertEqual(response.status_code, 403)

    def test_manual_entry_rejects_negative_and_unbounded(self):
        self.client.force_login(self.admin)
        acc_571 = Account.objects.get(code='571')
        acc_701 = Account.objects.get(code='701')
        data = {
            'date': timezone.now().date().isoformat(), 'description': 'Test',
            'line_count': '2',
            'account_0': acc_571.pk, 'debit_0': '-100', 'credit_0': '0',
            'account_1': acc_701.pk, 'debit_1': '0', 'credit_1': '-100',
        }
        self.client.post(reverse('accounting_add_entry'), data)
        self.assertFalse(JournalEntry.objects.filter(journal='OD').exists())
        data['line_count'] = '100000000'
        data.update({'debit_0': '100', 'credit_1': '100'})
        response = self.client.post(reverse('accounting_add_entry'), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(JournalEntry.objects.filter(journal='OD').count(), 1)

    def test_chart_import_restricted_and_protects_system_accounts(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.cashier)
        _grant(self.cashier, 'accounting')
        csv_bytes = 'Code;Libellé;Type;Parent;Description;Actif\n701;Ventes;ACTIF;;;non\n'.encode('utf-8')
        response = self.client.post(reverse('import_chart_of_accounts'),
                                    {'file': SimpleUploadedFile('plan.csv', csv_bytes)})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Account.objects.get(code='701').is_active)
        self.client.force_login(self.admin)
        self.client.post(reverse('import_chart_of_accounts'), {'file': SimpleUploadedFile('plan.csv', csv_bytes)})
        acc = Account.objects.get(code='701')
        self.assertTrue(acc.is_active)
        self.assertEqual(acc.account_type, 'PRODUIT')
        self.assertEqual(acc.name, 'Ventes')

    def test_csv_export_neutralises_formulas(self):
        self.client.force_login(self.admin)
        Account.objects.create(code='9999', name='=HYPERLINK("http://evil")', account_type='CHARGE')
        response = self.client.get(reverse('export_chart_of_accounts'))
        self.assertIn("'=HYPERLINK", response.content.decode('utf-8-sig'))
        self.assertEqual(self.client.get(reverse('export_chart_of_accounts') + '?format=html').status_code, 400)

    def test_supplier_payment_cannot_exceed_remaining(self):
        self.client.force_login(self.admin)
        daily = DailyService.get_or_create_active_daily()
        supplier = Supplier.objects.create(name='Fournisseur A')
        other = Supplier.objects.create(name='Fournisseur B')
        supply = Supply.objects.create(
            product=self.product, supplier=supplier, staff=self.admin, daily=daily,
            quantity=5, purchase_cost=Decimal('100'), total_price=Decimal('500'),
            is_credit=True, is_paid=False,
        )
        url = reverse('record_supply_payment', args=[supply.pk])
        self.client.get(url)
        self.assertFalse(CreditSupply.objects.filter(supply=supply).exists())  # rien créé en GET
        response = self.client.post(url, {
            'supplier': other.pk, 'amount': '600', 'payment_method': 'CASH',
            'payment_date': timezone.now().date().isoformat(),
        })
        self.assertEqual(response.status_code, 200)  # formulaire ré-affiché avec erreur
        self.assertFalse(SupplierPayment.objects.exists())
        response = self.client.post(url, {
            'supplier': other.pk, 'amount': '300', 'payment_method': 'CASH',
            'payment_date': timezone.now().date().isoformat(),
        })
        self.assertEqual(response.status_code, 302)
        payment = SupplierPayment.objects.get()
        self.assertEqual(payment.supplier, supplier)  # fournisseur imposé
        self.assertEqual(payment.supply, supply)
        self.assertEqual(CreditSupply.objects.get(supply=supply).amount_remaining, Decimal('200'))


@override_settings(STATICFILES_STORAGE=STATIC_STORAGE)
class ExerciseClosingTests(SecurityTestBase):
    def test_inventory_close_does_not_close_exercise(self):
        from core.models import Inventory
        self.client.force_login(self.admin)
        exercise = Exercise.objects.create(start_date=timezone.now())
        Inventory.objects.create(product=self.product, staff=self.admin, exercise=exercise,
                                 valid_product_count=7, invalid_product_count=0)
        self.client.post(reverse('close_inventory_confirm'))
        exercise.refresh_from_db()
        self.assertIsNone(exercise.end_date)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 7)

    def test_close_exercise_is_not_replayable(self):
        self.client.force_login(self.admin)
        response = self.client.post('/api/sales/', {
            'items': [{'product_id': self.product.pk, 'quantity': 1, 'unit_price': '1000'}],
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        # Journée encore ouverte : clôture refusée
        self.client.post(reverse('close_exercise_action'))
        self.assertEqual(Exercise.objects.filter(end_date__isnull=False).count(), 0)
        DailyService.close_current_daily()
        self.client.post(reverse('close_exercise_action'))
        self.assertEqual(Exercise.objects.filter(end_date__isnull=False).count(), 1)
        self.assertEqual(Exercise.objects.filter(end_date__isnull=True).count(), 1)
        opened = Exercise.objects.get(end_date__isnull=True)
        # Second POST : le nouvel exercice est vide, rien ne doit être clôturé
        self.client.post(reverse('close_exercise_action'))
        self.assertEqual(Exercise.objects.filter(end_date__isnull=False).count(), 1)
        self.assertEqual(JournalEntry.objects.filter(exercise=opened, journal='AN').count(), 1)

    def test_expense_must_hit_class_6(self):
        from core.models import DailyExpense, ExpenseType
        daily = DailyService.get_or_create_active_daily()
        etype = ExpenseType.objects.create(name='Divers')
        expense = DailyExpense.objects.create(
            daily=daily, exercise=daily.exercise, staff=self.admin, expense_type=etype,
            amount=Decimal('1000'), account=Account.objects.get(code='411'),
        )
        with self.assertRaises(ValueError):
            AccountingService.record_expense(expense, daily, daily.exercise)
