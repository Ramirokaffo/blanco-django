import json
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    AppModule,
    CreditSale,
    CreditSupply,
    Client,
    Daily,
    DailyExpense,
    DailyRecipe,
    Exercise,
    ExpenseType,
    Invoice,
    JournalEntry,
    Product,
    Payment,
    PaymentSchedule,
    Refund,
    RecipeType,
    Sale,
    SaleReturn,
    SaleReturnLine,
    SaleProduct,
    Supply,
    SupplyReturn,
    Supplier,
    SupplierPayment,
    SystemSettings,
    TaxRate,
)
from core.services.accounting_service import AccountingService
from core.services.sale_service import SaleService
from core.services.supply_service import SupplyService


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class ProductPagesTests(TestCase):
    def setUp(self):
        AppModule.init_default_modules()
        self.user = get_user_model().objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='password123',
        )
        self.user.firstname = 'Admin'
        self.user.lastname = 'Principal'
        self.user.role = 'Administrateur'
        self.user.gender = 'M'
        self.user.save()
        self.sales_module = AppModule.objects.filter(code='sales').first()
        self.staff_member = get_user_model().objects.create_user(
            username='marie',
            email='marie@example.com',
            password='password123',
            firstname='Marie',
            lastname='Kaffo',
            role='Caissière',
            gender='F',
            is_active=False,
        )
        if self.sales_module:
            self.user.allowed_modules.add(self.sales_module)
            self.staff_member.allowed_modules.add(self.sales_module)
        self.client.force_login(self.user)
        self.product = Product.objects.create(
            code='PRD-001',
            name='Savon Premium',
            brand='Blanco',
            stock=12,
            actual_price=2500,
            max_salable_price=3000,
        )
        self.customer = Client.objects.create(
            firstname='Amina',
            lastname='Kaffo',
            email='amina@example.com',
            phone_number='670000000',
            gender='F',
        )
        self.supplier = Supplier.objects.create(
            name='Cosmétique Distribution',
            contact_phone='677000000',
            contact_email='contact@cosmetique.example',
            niu='SUP-001',
        )
        now = timezone.now()
        self.exercise = Exercise.objects.create(start_date=now)
        self.daily = Daily.objects.create(start_date=now, exercise=self.exercise)
        self.expense_type = ExpenseType.objects.create(name='Transport')
        self.recipe_type = RecipeType.objects.create(name='Services')
        self.daily_expense = DailyExpense.objects.create(
            amount=1200,
            description='Transport administratif',
            daily=self.daily,
            expense_type=self.expense_type,
            staff=self.user,
            exercise=self.exercise,
        )
        self.daily_recipe = DailyRecipe.objects.create(
            amount=4500,
            description='Commission prestation',
            daily=self.daily,
            recipe_type=self.recipe_type,
            staff=self.staff_member,
            exercise=self.exercise,
        )

    def test_product_detail_page_renders(self):
        response = self.client.get(reverse('product_detail', args=[self.product.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Détail du produit')
        self.assertContains(response, self.product.name)
        self.assertContains(response, self.product.code)

    def test_products_list_contains_detail_link(self):
        response = self.client.get(reverse('products'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('product_detail', args=[self.product.id]))

    def test_statistics_page_renders(self):
        response = self.client.get(reverse('statistics'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Statistiques du système')
        self.assertContains(response, 'Chiffre d\'affaires global')
        self.assertContains(response, 'Statistiques par domaine')
        self.assertContains(response, 'Personnel')
        self.assertContains(response, 'Gammes, catégories &amp; rayons', html=True)
        self.assertContains(response, reverse('product_statistics'))
        self.assertContains(response, reverse('sales_statistics'))
        self.assertContains(response, reverse('client_statistics'))
        self.assertContains(response, reverse('expense_statistics'))
        self.assertContains(response, reverse('supply_statistics'))
        self.assertContains(response, reverse('supplier_statistics'))
        self.assertContains(response, reverse('personnel_statistics'))

    def test_expense_statistics_page_renders(self):
        response = self.client.get(reverse('expense_statistics'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Statistiques dépenses & recettes')
        self.assertContains(response, 'Tendance dépenses / recettes / net')
        self.assertContains(response, 'name="period"', html=False)
        self.assertContains(response, 'name="expense_type"', html=False)
        self.assertContains(response, 'name="recipe_type"', html=False)
        self.assertContains(response, 'name="staff"', html=False)

    def test_expense_statistics_accepts_filters(self):
        today = timezone.localdate()
        response = self.client.get(reverse('expense_statistics'), {
            'period': 'custom',
            'search': 'Transport',
            'staff': str(self.user.id),
            'expense_type': str(self.expense_type.id),
            'recipe_type': str(self.recipe_type.id),
            'date_from': (today - timedelta(days=1)).isoformat(),
            'date_to': (today + timedelta(days=1)).isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Transport administratif')
        self.assertContains(response, 'Transport')

    def test_client_statistics_page_renders(self):
        response = self.client.get(reverse('client_statistics'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Statistiques clients')
        self.assertContains(response, 'Acquisition clients')
        self.assertContains(response, 'name="period"', html=False)
        self.assertContains(response, 'name="gender"', html=False)
        self.assertContains(response, 'name="activity"', html=False)

    def test_client_statistics_accepts_filters(self):
        response = self.client.get(reverse('client_statistics'), {
            'period': 'custom',
            'search': 'Amina',
            'gender': 'F',
            'activity': 'inactive',
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Amina')

    def test_supplier_statistics_page_renders(self):
        response = self.client.get(reverse('supplier_statistics'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Statistiques fournisseurs')
        self.assertContains(response, 'Acquisition fournisseurs')
        self.assertContains(response, 'name="period"', html=False)
        self.assertContains(response, 'name="activity"', html=False)

    def test_supplier_statistics_accepts_filters(self):
        response = self.client.get(reverse('supplier_statistics'), {
            'period': 'custom',
            'search': 'Cosmétique',
            'activity': 'inactive',
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cosmétique Distribution')

    def test_supply_statistics_page_renders(self):
        response = self.client.get(reverse('supply_statistics'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Statistiques approvisionnements')
        self.assertContains(response, 'Tendance montant / quantités')
        self.assertContains(response, 'name="period"', html=False)
        self.assertContains(response, 'name="supplier"', html=False)
        self.assertContains(response, 'name="staff"', html=False)

    def test_supply_statistics_accepts_filters(self):
        response = self.client.get(reverse('supply_statistics'), {
            'period': 'custom',
            'search': 'Savon',
            'supplier': str(self.supplier.id),
            'type': 'credit',
            'status': 'paid',
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Savon')

    def test_add_supply_page_exposes_product_price_metadata(self):
        self.product.last_purchase_price = Decimal('1800')
        self.product.actual_price = Decimal('2500')
        self.product.save(update_fields=['last_purchase_price', 'actual_price'])

        response = self.client.get(reverse('add_supply'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Prix de vente actuel')
        self.assertContains(response, 'Dernier coût d\'achat')

        form = response.context['form']
        product_meta_map = json.loads(form.fields['product'].widget.attrs['data-product-meta-map'])

        self.assertEqual(product_meta_map[str(self.product.id)]['selling_price'], '2500')
        self.assertEqual(product_meta_map[str(self.product.id)]['purchase_cost'], '1800')

    def test_add_supply_ajax_invalid_submission_returns_json_errors(self):
        self.product.has_vat = False
        self.product.save(update_fields=['has_vat'])

        response = self.client.post(
            reverse('add_supply'),
            {
                'product': self.product.id,
                'quantity': 5,
                'selling_price': '2600',
                'payment_method': 'CASH',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 400)

        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertIn('purchase_cost', payload['errors'])

    def test_product_statistics_page_renders(self):
        response = self.client.get(reverse('product_statistics'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Statistiques produits')
        self.assertContains(response, 'Tendance ventes / chiffre d\'affaires')
        self.assertContains(response, 'name="period"', html=False)
        self.assertContains(response, 'name="date_from"', html=False)
        self.assertContains(response, 'name="category"', html=False)

    def test_product_statistics_accepts_filters(self):
        response = self.client.get(reverse('product_statistics'), {
            'period': 'custom',
            'search': 'Savon',
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Savon')

    def test_sales_statistics_page_renders(self):
        response = self.client.get(reverse('sales_statistics'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Statistiques ventes')
        self.assertContains(response, 'Tendance chiffre d\'affaires / volume')
        self.assertContains(response, 'name="period"', html=False)
        self.assertContains(response, 'name="client"', html=False)
        self.assertContains(response, 'name="staff"', html=False)

    def test_sales_statistics_accepts_filters(self):
        response = self.client.get(reverse('sales_statistics'), {
            'period': 'custom',
            'search': 'Admin',
            'type': 'credit',
            'status': 'paid',
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Admin')

    def test_personnel_statistics_page_renders(self):
        response = self.client.get(reverse('personnel_statistics'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Statistiques personnel')
        self.assertContains(response, 'Répartition des statuts')
        self.assertContains(response, 'name="period"', html=False)
        self.assertContains(response, 'name="status"', html=False)
        self.assertContains(response, 'name="module"', html=False)

    def test_personnel_statistics_accepts_filters(self):
        response = self.client.get(reverse('personnel_statistics'), {
            'period': 'custom',
            'search': 'Marie',
            'status': 'inactive',
            'role': 'Caissière',
            'gender': 'F',
            'module': 'sales',
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Marie')
        self.assertContains(response, 'Caissière')

    def test_dashboard_navigation_contains_statistics_tab(self):
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('statistics'))
        self.assertContains(response, 'Statistiques')

    def test_dashboard_renders_sidebar_shell(self):
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="sidebarToggle"', html=False)
        self.assertContains(response, 'id="appSidebar"', html=False)
        self.assertContains(response, 'id="sidebarBackdrop"', html=False)


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class SalesCancellationTests(TestCase):
    def setUp(self):
        AppModule.init_default_modules()
        self.user = get_user_model().objects.create_superuser(
            username='admin-sales',
            email='admin-sales@example.com',
            password='password123',
        )
        self.user.firstname = 'Admin'
        self.user.lastname = 'Ventes'
        self.user.role = 'Administrateur'
        self.user.gender = 'M'
        self.user.save()
        self.client.force_login(self.user)

        AccountingService.init_chart_of_accounts()
        settings_obj = SystemSettings.get_settings()
        settings_obj.enable_tva_accounting = True
        settings_obj.tva_accounting_mode = 'IMMEDIATE'
        settings_obj.save()

        self.tax_rate = TaxRate.objects.create(
            name='TVA standard',
            rate=Decimal('19.25'),
            is_default=True,
            is_active=True,
        )
        now = timezone.now()
        self.exercise = Exercise.objects.create(start_date=now)
        self.daily = Daily.objects.create(start_date=now, exercise=self.exercise)
        self.customer = Client.objects.create(
            firstname='Amina',
            lastname='Ngono',
            email='amina.ngono@example.com',
            phone_number='670000111',
            gender='F',
        )

    def _create_product(self, code='PRD-001', name='Savon Premium', stock=10, has_vat=True):
        return Product.objects.create(
            code=code,
            name=name,
            brand='Blanco',
            stock=stock,
            actual_price=Decimal('11925'),
            max_salable_price=Decimal('15000'),
            has_vat=has_vat,
        )

    def _create_sale(self, product, *, is_credit=False, total='11925', quantity=1, apply_tax=True, payment_method='CASH'):
        total_amount = Decimal(total)
        sale = Sale.objects.create(
            client=self.customer,
            staff=self.user,
            daily=self.daily,
            total=total_amount,
            is_credit=is_credit,
            is_paid=not is_credit,
            has_vat=product.has_vat,
        )
        SaleProduct.objects.create(
            sale=sale,
            product=product,
            quantity=quantity,
            unit_price=total_amount / quantity,
        )
        product.stock -= quantity
        product.save(update_fields=['stock'])
        AccountingService.record_sale(
            sale=sale,
            daily=self.daily,
            exercise=self.exercise,
            payment_method=payment_method,
            apply_tax=apply_tax,
        )
        return sale

    def test_record_deferred_tva_creates_balanced_entry(self):
        settings_obj = SystemSettings.get_settings()
        settings_obj.tva_accounting_mode = 'DEFERRED'
        settings_obj.save(update_fields=['tva_accounting_mode'])

        product = self._create_product(code='PRD-TVA', name='Gel douche TVA')
        sale = self._create_sale(product, apply_tax=False)

        created_count = AccountingService.record_deferred_tva_for_daily(self.daily)

        self.assertEqual(created_count, 1)
        sale.refresh_from_db()
        self.assertTrue(sale.tva_accounting_created)

        entry = JournalEntry.objects.filter(
            sale=sale,
            description__icontains='TVA collectée',
        ).order_by('-id').first()
        self.assertIsNotNone(entry)
        self.assertTrue(entry.is_balanced())
        self.assertEqual(entry.lines.count(), 2)
        self.assertEqual(entry.lines.get(account__code='701').debit, Decimal('1925.00'))
        self.assertEqual(entry.lines.get(account__code='4431').credit, Decimal('1925.00'))

    def test_cancel_cash_sale_restores_stock_creates_refund_and_cancels_invoice(self):
        product = self._create_product(code='PRD-CASH', name='Savon comptant')
        sale = self._create_sale(product, is_credit=False, apply_tax=True)
        invoice = Invoice.objects.create(
            sale=sale,
            invoice_number='FAC-TEST-CASH-001',
            invoice_date=timezone.localdate(),
            status='SENT',
        )

        refund_amount = SaleService.cancel_sale(
            sale=sale,
            reason='Retour client',
            refund_payment_method='CASH',
        )

        sale.refresh_from_db()
        product.refresh_from_db()
        invoice.refresh_from_db()
        refund = Refund.objects.get(sale=sale)
        cancellation_entry = JournalEntry.objects.filter(
            sale=sale,
            description=f'Annulation vente #{sale.id}',
        ).first()

        self.assertEqual(refund_amount, Decimal('11925'))
        self.assertIsNotNone(sale.delete_at)
        self.assertEqual(product.stock, 10)
        self.assertEqual(refund.value, Decimal('11925.00'))
        self.assertEqual(invoice.status, 'CANCELLED')
        self.assertIn('Retour client', invoice.notes)
        self.assertIsNotNone(cancellation_entry)
        self.assertTrue(cancellation_entry.is_balanced())
        self.assertEqual(cancellation_entry.lines.get(account__code='701').debit, Decimal('10000.00'))
        self.assertEqual(cancellation_entry.lines.get(account__code='4431').debit, Decimal('1925.00'))
        self.assertEqual(cancellation_entry.lines.get(account__code='571').credit, Decimal('11925.00'))

    def test_cancel_credit_sale_with_partial_payment_refunds_only_collected_amount(self):
        product = self._create_product(code='PRD-CREDIT', name='Savon crédit')
        sale = self._create_sale(product, is_credit=True, apply_tax=True)
        credit_sale = CreditSale.objects.create(
            sale=sale,
            amount_paid=Decimal('5000'),
            amount_remaining=Decimal('6925'),
            due_date=timezone.localdate() + timedelta(days=30),
            is_fully_paid=False,
        )
        schedule = PaymentSchedule.objects.create(
            schedule_type='CLIENT',
            credit_sale=credit_sale,
            due_date=timezone.localdate() + timedelta(days=30),
            amount_due=Decimal('6925'),
            amount_paid=Decimal('0'),
            status='PENDING',
        )
        payment = Payment.objects.create(
            credit_sale=credit_sale,
            amount=Decimal('5000'),
            payment_method='BANK_TRANSFER',
            payment_date=timezone.localdate(),
            staff=self.user,
            daily=self.daily,
        )
        AccountingService.record_credit_payment(payment, self.daily, self.exercise)

        refund_amount = SaleService.cancel_sale(
            sale=sale,
            reason='Retour après acompte',
            refund_payment_method='BANK_TRANSFER',
        )

        sale.refresh_from_db()
        credit_sale.refresh_from_db()
        schedule.refresh_from_db()
        product.refresh_from_db()
        refund = Refund.objects.get(sale=sale)
        reversal_entry = JournalEntry.objects.get(
            sale=sale,
            description=f'Annulation vente #{sale.id}',
        )
        refund_entry = JournalEntry.objects.get(
            sale=sale,
            description=f'Remboursement client – annulation vente #{sale.id}',
        )

        self.assertEqual(refund_amount, Decimal('5000'))
        self.assertIsNotNone(sale.delete_at)
        self.assertIsNotNone(credit_sale.delete_at)
        self.assertIsNotNone(schedule.delete_at)
        self.assertEqual(product.stock, 10)
        self.assertEqual(refund.value, Decimal('5000.00'))
        self.assertTrue(reversal_entry.is_balanced())
        self.assertTrue(refund_entry.is_balanced())
        self.assertEqual(reversal_entry.lines.get(account__code='411').credit, Decimal('11925.00'))
        self.assertEqual(refund_entry.lines.get(account__code='411').debit, Decimal('5000.00'))
        self.assertEqual(refund_entry.lines.get(account__code='521').credit, Decimal('5000.00'))

    def test_sales_history_cancel_view_redirects_and_filters_cancelled_sales(self):
        product = self._create_product(code='PRD-VIEW', name='Savon vue')
        sale = self._create_sale(product, is_credit=False, apply_tax=True)

        response = self.client.post(
            reverse('cancel_sale', args=[sale.id]),
            {
                'reason': 'Retour client comptoir',
                'refund_payment_method': 'CASH',
                'next': reverse('sales_history') + '?status=cancelled',
            },
            follow=True,
        )

        sale.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(sale.delete_at)
        self.assertContains(response, f'Vente #{sale.id} annulée')
        self.assertContains(response, 'Annulée')

        cancelled_response = self.client.get(reverse('sales_history'), {'status': 'cancelled'})
        paid_response = self.client.get(reverse('sales_history'), {'status': 'paid'})

        self.assertEqual(cancelled_response.status_code, 200)
        self.assertIn(sale.id, [obj.id for obj in cancelled_response.context['sales']])
        self.assertNotIn(sale.id, [obj.id for obj in paid_response.context['sales']])

    def test_partial_return_cash_sale_updates_stock_audit_invoice_and_accounting(self):
        product = self._create_product(code='PRD-RETURN-CASH', name='Savon retour cash')
        sale = self._create_sale(product, is_credit=False, total='23850', quantity=2, apply_tax=True)
        invoice = Invoice.objects.create(
            sale=sale,
            invoice_number='FAC-TEST-RETURN-001',
            invoice_date=timezone.localdate(),
            status='SENT',
        )
        sale_product = sale.sale_products.get()

        sale_return, refund_amount = SaleService.partial_return_sale(
            sale=sale,
            returned_items=[{'sale_product': sale_product, 'quantity': 1}],
            reason='Retour d\'une unité',
            refund_payment_method='CASH',
        )

        sale.refresh_from_db()
        sale_product.refresh_from_db()
        product.refresh_from_db()
        invoice.refresh_from_db()
        refund = Refund.objects.get(sale=sale)
        return_line = SaleReturnLine.objects.get(sale_return=sale_return)
        entry = JournalEntry.objects.get(sale=sale, description=f'Retour partiel vente #{sale.id}')

        self.assertEqual(refund_amount, Decimal('11925.00'))
        self.assertEqual(sale.total, Decimal('11925.00'))
        self.assertEqual(product.stock, 9)
        self.assertEqual(sale_product.quantity, 1)
        self.assertEqual(sale_return.total, Decimal('11925.00'))
        self.assertEqual(return_line.quantity, 1)
        self.assertEqual(refund.value, Decimal('11925.00'))
        self.assertEqual(invoice.status, 'SENT')
        self.assertIn('Retour partiel', invoice.notes)
        self.assertTrue(entry.is_balanced())
        self.assertEqual(entry.lines.get(account__code='701').debit, Decimal('10000.00'))
        self.assertEqual(entry.lines.get(account__code='4431').debit, Decimal('1925.00'))
        self.assertEqual(entry.lines.get(account__code='571').credit, Decimal('11925.00'))

    def test_partial_return_credit_sale_without_refund_reduces_balance_only(self):
        product = self._create_product(code='PRD-RETURN-CREDIT', name='Savon retour crédit')
        sale = self._create_sale(product, is_credit=True, total='23850', quantity=2, apply_tax=True)
        credit_sale = CreditSale.objects.create(
            sale=sale,
            amount_paid=Decimal('5000.00'),
            amount_remaining=Decimal('18850.00'),
            due_date=timezone.localdate() + timedelta(days=30),
            is_fully_paid=False,
        )
        schedule = PaymentSchedule.objects.create(
            schedule_type='CLIENT',
            credit_sale=credit_sale,
            due_date=timezone.localdate() + timedelta(days=30),
            amount_due=Decimal('23850.00'),
            amount_paid=Decimal('0.00'),
            status='PENDING',
        )
        sale_product = sale.sale_products.get()

        sale_return, refund_amount = SaleService.partial_return_sale(
            sale=sale,
            returned_items=[{'sale_product': sale_product, 'quantity': 1}],
            reason='Retour sans trop-perçu',
            refund_payment_method='BANK_TRANSFER',
        )

        sale.refresh_from_db()
        credit_sale.refresh_from_db()
        schedule.refresh_from_db()
        sale_product.refresh_from_db()
        product.refresh_from_db()
        entry = JournalEntry.objects.get(sale=sale, description=f'Retour partiel vente #{sale.id}')

        self.assertEqual(sale_return.total, Decimal('11925.00'))
        self.assertEqual(refund_amount, Decimal('0.00'))
        self.assertEqual(sale.total, Decimal('11925.00'))
        self.assertEqual(credit_sale.amount_paid, Decimal('5000.00'))
        self.assertEqual(credit_sale.amount_remaining, Decimal('6925.00'))
        self.assertFalse(credit_sale.is_fully_paid)
        self.assertFalse(sale.is_paid)
        self.assertEqual(schedule.amount_due, Decimal('11925.00'))
        self.assertEqual(sale_product.quantity, 1)
        self.assertEqual(product.stock, 9)
        self.assertFalse(Refund.objects.filter(sale=sale).exists())
        self.assertTrue(entry.is_balanced())
        self.assertEqual(entry.lines.get(account__code='411').credit, Decimal('11925.00'))

    def test_partial_return_credit_sale_with_overpayment_creates_refund_and_updates_credit(self):
        product = self._create_product(code='PRD-RETURN-OVER', name='Savon retour trop-perçu')
        sale = self._create_sale(product, is_credit=True, total='23850', quantity=2, apply_tax=True)
        credit_sale = CreditSale.objects.create(
            sale=sale,
            amount_paid=Decimal('18000.00'),
            amount_remaining=Decimal('5850.00'),
            due_date=timezone.localdate() + timedelta(days=30),
            is_fully_paid=False,
        )
        schedule = PaymentSchedule.objects.create(
            schedule_type='CLIENT',
            credit_sale=credit_sale,
            due_date=timezone.localdate() + timedelta(days=30),
            amount_due=Decimal('23850.00'),
            amount_paid=Decimal('0.00'),
            status='PENDING',
        )
        payment = Payment.objects.create(
            credit_sale=credit_sale,
            amount=Decimal('18000.00'),
            payment_method='BANK_TRANSFER',
            payment_date=timezone.localdate(),
            staff=self.user,
            daily=self.daily,
        )
        AccountingService.record_credit_payment(payment, self.daily, self.exercise)
        sale_product = sale.sale_products.get()

        sale_return, refund_amount = SaleService.partial_return_sale(
            sale=sale,
            returned_items=[{'sale_product': sale_product, 'quantity': 1}],
            reason='Retour avec trop-perçu',
            refund_payment_method='BANK_TRANSFER',
        )

        sale.refresh_from_db()
        credit_sale.refresh_from_db()
        schedule.refresh_from_db()
        sale_product.refresh_from_db()
        refund = Refund.objects.get(sale=sale)
        reversal_entry = JournalEntry.objects.get(sale=sale, description=f'Retour partiel vente #{sale.id}')
        refund_entry = JournalEntry.objects.get(sale=sale, description=f'Remboursement client – retour partiel vente #{sale.id}')

        self.assertEqual(sale_return.total, Decimal('11925.00'))
        self.assertEqual(refund_amount, Decimal('6075.00'))
        self.assertEqual(sale.total, Decimal('11925.00'))
        self.assertEqual(credit_sale.amount_paid, Decimal('11925.00'))
        self.assertEqual(credit_sale.amount_remaining, Decimal('0.00'))
        self.assertTrue(credit_sale.is_fully_paid)
        self.assertTrue(sale.is_paid)
        self.assertEqual(schedule.amount_due, Decimal('11925.00'))
        self.assertEqual(refund.value, Decimal('6075.00'))
        self.assertTrue(reversal_entry.is_balanced())
        self.assertTrue(refund_entry.is_balanced())
        self.assertEqual(reversal_entry.lines.get(account__code='411').credit, Decimal('11925.00'))
        self.assertEqual(refund_entry.lines.get(account__code='411').debit, Decimal('6075.00'))
        self.assertEqual(refund_entry.lines.get(account__code='521').credit, Decimal('6075.00'))

    def test_sales_history_partial_return_view_redirects_and_updates_net_sale(self):
        product = self._create_product(code='PRD-VIEW-RETURN', name='Savon vue retour')
        sale = self._create_sale(product, is_credit=False, total='23850', quantity=2, apply_tax=True)
        sale_product = sale.sale_products.get()

        response = self.client.post(
            reverse('partial_return_sale', args=[sale.id]),
            {
                'reason': 'Retour partiel comptoir',
                'refund_payment_method': 'CASH',
                f'return_quantity_{sale_product.id}': '1',
                'next': reverse('sales_history'),
            },
            follow=True,
        )

        sale.refresh_from_db()
        sale_product.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'Retour partiel enregistré sur la vente #{sale.id}')
        self.assertEqual(sale.total, Decimal('11925.00'))
        self.assertEqual(sale_product.quantity, 1)
        self.assertTrue(SaleReturn.objects.filter(sale=sale).exists())

        sales_response = self.client.get(reverse('sales_history'))
        products_response = self.client.get(reverse('sales_history'), {'view_mode': 'products'})

        self.assertEqual(sales_response.status_code, 200)
        self.assertEqual(products_response.status_code, 200)
        self.assertContains(sales_response, '11925')
        self.assertIn(sale_product.id, [obj.id for obj in products_response.context['sale_products']])


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class SupplyCancellationTests(TestCase):
    def setUp(self):
        AppModule.init_default_modules()
        self.user = get_user_model().objects.create_superuser(
            username='admin-supplies',
            email='admin-supplies@example.com',
            password='password123',
        )
        self.user.firstname = 'Admin'
        self.user.lastname = 'Achats'
        self.user.role = 'Administrateur'
        self.user.gender = 'M'
        self.user.save()
        self.client.force_login(self.user)

        AccountingService.init_chart_of_accounts()
        settings_obj = SystemSettings.get_settings()
        settings_obj.enable_tva_accounting = True
        settings_obj.tva_accounting_mode = 'IMMEDIATE'
        settings_obj.save()

        self.tax_rate = TaxRate.objects.create(
            name='TVA standard achats',
            rate=Decimal('19.25'),
            is_default=False,
            is_active=True,
        )
        now = timezone.now()
        self.exercise = Exercise.objects.create(start_date=now)
        self.daily = Daily.objects.create(start_date=now, exercise=self.exercise)
        self.supplier = Supplier.objects.create(
            name='Fournisseur Blanc',
            contact_phone='677123456',
            contact_email='fournisseur@example.com',
            niu='SUP-RET-001',
        )

    def _create_product(self, code='SUP-001', name='Savon fournisseur', stock=10, has_vat=True):
        return Product.objects.create(
            code=code,
            name=name,
            brand='Blanco',
            stock=stock,
            actual_price=Decimal('15000'),
            max_salable_price=Decimal('18000'),
            has_vat=has_vat,
        )

    def _create_supply(self, product, *, is_credit=False, total='11925', quantity=1, apply_tax=True, payment_method='CASH'):
        total_amount = Decimal(total)
        tax_rate = self.tax_rate if apply_tax else None
        _, vat_amount = AccountingService.compute_tax(total_amount, tax_rate)
        supply = Supply.objects.create(
            product=product,
            supplier=self.supplier,
            staff=self.user,
            daily=self.daily,
            quantity=quantity,
            purchase_cost=total_amount / quantity,
            selling_price=Decimal('15000'),
            total_price=total_amount,
            is_credit=is_credit,
            is_paid=not is_credit,
            tax_rate=tax_rate,
            vat_amount=vat_amount,
        )
        product.stock = (product.stock or 0) + quantity
        product.save(update_fields=['stock'])
        AccountingService.record_supply(
            supply=supply,
            daily=self.daily,
            exercise=self.exercise,
            payment_method=payment_method,
            is_credit=is_credit,
            tax_rate=tax_rate,
        )
        return supply

    def test_cancel_cash_supply_restores_stock_and_records_accounting(self):
        product = self._create_product(code='SUP-CASH', name='Appro comptant')
        supply = self._create_supply(product, is_credit=False, apply_tax=True)

        refund_amount = SupplyService.cancel_supply(
            supply=supply,
            reason='Retour fournisseur total',
            refund_payment_method='CASH',
        )

        supply.refresh_from_db()
        product.refresh_from_db()
        cancellation_entry = JournalEntry.objects.get(
            supply=supply,
            description=f'Annulation approvisionnement #{supply.id}',
        )

        self.assertEqual(refund_amount, Decimal('11925'))
        self.assertIsNotNone(supply.delete_at)
        self.assertEqual(product.stock, 10)
        self.assertTrue(cancellation_entry.is_balanced())
        self.assertEqual(cancellation_entry.lines.get(account__code='601').credit, Decimal('10000.00'))
        self.assertEqual(cancellation_entry.lines.get(account__code='4451').credit, Decimal('1925.00'))
        self.assertEqual(cancellation_entry.lines.get(account__code='571').debit, Decimal('11925.00'))

    def test_cancel_credit_supply_with_partial_payment_refunds_only_paid_amount(self):
        product = self._create_product(code='SUP-CREDIT', name='Appro crédit')
        supply = self._create_supply(product, is_credit=True, apply_tax=True)
        credit_supply = CreditSupply.objects.create(
            supply=supply,
            amount_paid=Decimal('5000.00'),
            amount_remaining=Decimal('6925.00'),
            due_date=timezone.localdate() + timedelta(days=30),
            is_fully_paid=False,
        )
        schedule = PaymentSchedule.objects.create(
            schedule_type='SUPPLIER',
            credit_supply=credit_supply,
            due_date=timezone.localdate() + timedelta(days=30),
            amount_due=Decimal('6925.00'),
            amount_paid=Decimal('0.00'),
            status='PENDING',
        )
        payment = SupplierPayment.objects.create(
            supplier=self.supplier,
            supply=supply,
            amount=Decimal('5000.00'),
            payment_method='BANK_TRANSFER',
            payment_date=timezone.localdate(),
            staff=self.user,
            daily=self.daily,
        )
        AccountingService.record_supplier_payment(payment, self.daily, self.exercise)

        refund_amount = SupplyService.cancel_supply(
            supply=supply,
            reason='Retour après acompte fournisseur',
            refund_payment_method='BANK_TRANSFER',
        )

        supply.refresh_from_db()
        credit_supply.refresh_from_db()
        schedule.refresh_from_db()
        product.refresh_from_db()
        reversal_entry = JournalEntry.objects.get(
            supply=supply,
            description=f'Annulation approvisionnement #{supply.id}',
        )
        refund_entry = JournalEntry.objects.get(
            supply=supply,
            description=f'Remboursement fournisseur – annulation approvisionnement #{supply.id}',
        )

        self.assertEqual(refund_amount, Decimal('5000.00'))
        self.assertIsNotNone(supply.delete_at)
        self.assertIsNotNone(credit_supply.delete_at)
        self.assertIsNotNone(schedule.delete_at)
        self.assertEqual(product.stock, 10)
        self.assertTrue(reversal_entry.is_balanced())
        self.assertTrue(refund_entry.is_balanced())
        self.assertEqual(reversal_entry.lines.get(account__code='401').debit, Decimal('11925.00'))
        self.assertEqual(refund_entry.lines.get(account__code='401').credit, Decimal('5000.00'))
        self.assertEqual(refund_entry.lines.get(account__code='521').debit, Decimal('5000.00'))

    def test_partial_return_cash_supply_updates_stock_audit_and_accounting(self):
        product = self._create_product(code='SUP-RETURN-CASH', name='Appro retour cash')
        supply = self._create_supply(product, is_credit=False, total='23850', quantity=2, apply_tax=True)

        supply_return, refund_amount = SupplyService.partial_return_supply(
            supply=supply,
            returned_quantity=1,
            reason='Retour d\'une unité',
            refund_payment_method='CASH',
        )

        supply.refresh_from_db()
        product.refresh_from_db()
        entry = JournalEntry.objects.get(
            supply=supply,
            description=f'Retour partiel approvisionnement #{supply.id}',
        )

        self.assertEqual(refund_amount, Decimal('11925.00'))
        self.assertEqual(supply.quantity, 1)
        self.assertEqual(supply.total_price, Decimal('11925.00'))
        self.assertEqual(product.stock, 11)
        self.assertEqual(supply_return.total, Decimal('11925.00'))
        self.assertEqual(supply_return.refund_amount, Decimal('11925.00'))
        self.assertTrue(entry.is_balanced())
        self.assertEqual(entry.lines.get(account__code='601').credit, Decimal('10000.00'))
        self.assertEqual(entry.lines.get(account__code='4451').credit, Decimal('1925.00'))
        self.assertEqual(entry.lines.get(account__code='571').debit, Decimal('11925.00'))

    def test_partial_return_credit_supply_without_refund_reduces_balance_only(self):
        product = self._create_product(code='SUP-RETURN-CREDIT', name='Appro retour crédit')
        supply = self._create_supply(product, is_credit=True, total='23850', quantity=2, apply_tax=True)
        credit_supply = CreditSupply.objects.create(
            supply=supply,
            amount_paid=Decimal('5000.00'),
            amount_remaining=Decimal('18850.00'),
            due_date=timezone.localdate() + timedelta(days=30),
            is_fully_paid=False,
        )
        schedule = PaymentSchedule.objects.create(
            schedule_type='SUPPLIER',
            credit_supply=credit_supply,
            due_date=timezone.localdate() + timedelta(days=30),
            amount_due=Decimal('23850.00'),
            amount_paid=Decimal('0.00'),
            status='PENDING',
        )

        supply_return, refund_amount = SupplyService.partial_return_supply(
            supply=supply,
            returned_quantity=1,
            reason='Retour sans trop-perçu',
            refund_payment_method='BANK_TRANSFER',
        )

        supply.refresh_from_db()
        credit_supply.refresh_from_db()
        schedule.refresh_from_db()
        product.refresh_from_db()
        entry = JournalEntry.objects.get(
            supply=supply,
            description=f'Retour partiel approvisionnement #{supply.id}',
        )

        self.assertEqual(supply_return.total, Decimal('11925.00'))
        self.assertEqual(refund_amount, Decimal('0.00'))
        self.assertEqual(supply.quantity, 1)
        self.assertEqual(supply.total_price, Decimal('11925.00'))
        self.assertEqual(credit_supply.amount_paid, Decimal('5000.00'))
        self.assertEqual(credit_supply.amount_remaining, Decimal('6925.00'))
        self.assertFalse(credit_supply.is_fully_paid)
        self.assertFalse(supply.is_paid)
        self.assertEqual(schedule.amount_due, Decimal('11925.00'))
        self.assertEqual(product.stock, 11)
        self.assertEqual(supply_return.refund_amount, Decimal('0.00'))
        self.assertIsNone(supply_return.refund_payment_method)
        self.assertTrue(entry.is_balanced())
        self.assertEqual(entry.lines.get(account__code='401').debit, Decimal('11925.00'))
        self.assertFalse(
            JournalEntry.objects.filter(
                supply=supply,
                description=f'Remboursement fournisseur – retour partiel approvisionnement #{supply.id}',
            ).exists()
        )

    def test_partial_return_credit_supply_with_overpayment_creates_refund_and_updates_credit(self):
        product = self._create_product(code='SUP-RETURN-OVER', name='Appro retour trop-perçu')
        supply = self._create_supply(product, is_credit=True, total='23850', quantity=2, apply_tax=True)
        credit_supply = CreditSupply.objects.create(
            supply=supply,
            amount_paid=Decimal('18000.00'),
            amount_remaining=Decimal('5850.00'),
            due_date=timezone.localdate() + timedelta(days=30),
            is_fully_paid=False,
        )
        schedule = PaymentSchedule.objects.create(
            schedule_type='SUPPLIER',
            credit_supply=credit_supply,
            due_date=timezone.localdate() + timedelta(days=30),
            amount_due=Decimal('23850.00'),
            amount_paid=Decimal('0.00'),
            status='PENDING',
        )
        payment = SupplierPayment.objects.create(
            supplier=self.supplier,
            supply=supply,
            amount=Decimal('18000.00'),
            payment_method='BANK_TRANSFER',
            payment_date=timezone.localdate(),
            staff=self.user,
            daily=self.daily,
        )
        AccountingService.record_supplier_payment(payment, self.daily, self.exercise)

        supply_return, refund_amount = SupplyService.partial_return_supply(
            supply=supply,
            returned_quantity=1,
            reason='Retour avec trop-perçu',
            refund_payment_method='BANK_TRANSFER',
        )

        supply.refresh_from_db()
        credit_supply.refresh_from_db()
        schedule.refresh_from_db()
        refund_entry = JournalEntry.objects.get(
            supply=supply,
            description=f'Remboursement fournisseur – retour partiel approvisionnement #{supply.id}',
        )
        reversal_entry = JournalEntry.objects.get(
            supply=supply,
            description=f'Retour partiel approvisionnement #{supply.id}',
        )

        self.assertEqual(supply_return.total, Decimal('11925.00'))
        self.assertEqual(refund_amount, Decimal('6075.00'))
        self.assertEqual(supply.quantity, 1)
        self.assertEqual(supply.total_price, Decimal('11925.00'))
        self.assertEqual(credit_supply.amount_paid, Decimal('11925.00'))
        self.assertEqual(credit_supply.amount_remaining, Decimal('0.00'))
        self.assertTrue(credit_supply.is_fully_paid)
        self.assertTrue(supply.is_paid)
        self.assertEqual(schedule.amount_due, Decimal('11925.00'))
        self.assertEqual(supply_return.refund_amount, Decimal('6075.00'))
        self.assertTrue(reversal_entry.is_balanced())
        self.assertTrue(refund_entry.is_balanced())
        self.assertEqual(reversal_entry.lines.get(account__code='401').debit, Decimal('11925.00'))
        self.assertEqual(refund_entry.lines.get(account__code='401').credit, Decimal('6075.00'))
        self.assertEqual(refund_entry.lines.get(account__code='521').debit, Decimal('6075.00'))

    def test_supplies_cancel_view_redirects_and_hides_cancelled_supply(self):
        product = self._create_product(code='SUP-VIEW', name='Appro vue')
        supply = self._create_supply(product, is_credit=False, apply_tax=True)

        response = self.client.post(
            reverse('cancel_supply', args=[supply.id]),
            {
                'reason': 'Retour réception',
                'refund_payment_method': 'CASH',
                'next': reverse('supplies') + '?search=Appro',
            },
            follow=True,
        )

        supply.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(supply.delete_at)
        self.assertContains(response, f'Approvisionnement #{supply.id} annulé')
        self.assertNotIn(supply.id, [obj.id for obj in response.context['supplies']])

    def test_supplies_partial_return_view_redirects_updates_supply_and_shows_return_count(self):
        product = self._create_product(code='SUP-VIEW-RETURN', name='Appro vue retour')
        supply = self._create_supply(product, is_credit=False, total='23850', quantity=2, apply_tax=True)

        response = self.client.post(
            reverse('partial_return_supply', args=[supply.id]),
            {
                'reason': 'Retour partiel réception',
                'refund_payment_method': 'CASH',
                'returned_quantity': '1',
                'next': reverse('supplies'),
            },
            follow=True,
        )

        supply.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        messages = [str(message) for message in response.context['messages']]
        self.assertTrue(
            any(f"Retour partiel enregistré sur l'approvisionnement #{supply.id}" in message for message in messages)
        )
        self.assertEqual(supply.quantity, 1)
        self.assertEqual(supply.total_price, Decimal('11925.00'))
        self.assertTrue(SupplyReturn.objects.filter(supply=supply).exists())
        self.assertContains(response, '1 retour partiel enregistré')