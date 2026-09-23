import json
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    AppModule,
    Category,
    CreditSale,
    CreditSupply,
    Client,
    Daily,
    DailyExpense,
    DailyRecipe,
    Exercise,
    ExpenseType,
    Gamme,
    GrammageType,
    Invoice,
    JournalEntry,
    Product,
    Payment,
    PaymentSchedule,
    PurchaseOrder,
    Rayon,
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
from core.serializers.sale_serializers import SaleCreateSerializer


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

    def test_record_sale_applies_vat_only_to_taxable_lines(self):
        """Un panier mixte (produit exonéré + produit taxable) ne doit taxer que la part taxable."""
        taxable_product = self._create_product(code='PRD-TAXABLE', name='Savon taxable', has_vat=True)
        exempt_product = self._create_product(code='PRD-EXEMPT', name='Pain exonéré', has_vat=False)

        taxable_amount = Decimal('11925')
        exempt_amount = Decimal('5000')
        total = taxable_amount + exempt_amount

        sale = Sale.objects.create(
            client=self.customer,
            staff=self.user,
            daily=self.daily,
            total=total,
            is_credit=False,
            is_paid=True,
            has_vat=True,
        )
        SaleProduct.objects.create(sale=sale, product=taxable_product, quantity=1, unit_price=taxable_amount)
        SaleProduct.objects.create(sale=sale, product=exempt_product, quantity=1, unit_price=exempt_amount)

        entry = AccountingService.record_sale(
            sale=sale,
            daily=self.daily,
            exercise=self.exercise,
            payment_method='CASH',
            apply_tax=True,
        )

        self.assertIsNotNone(entry)
        self.assertTrue(entry.is_balanced())
        # TVA calculée uniquement sur la part taxable (11925 TTC à 19.25% -> 1925 de TVA)
        self.assertEqual(entry.lines.get(account__code='4431').credit, Decimal('1925'))
        self.assertEqual(entry.lines.get(account__code='701').credit, total - Decimal('1925'))
        self.assertEqual(entry.lines.get(account__code='571').debit, total)

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

class DefaultDataSeedingTests(TestCase):
    """Chargement des données de référence (modules applicatifs, plan comptable)."""

    def test_default_data_is_seeded_after_migrate(self):
        # Le signal post_migrate a tourné lors de la création de la base de test
        from core.models.settings_models import DEFAULT_MODULES
        from core.services.accounting_service import DEFAULT_ACCOUNTS
        from core.models import Account

        self.assertEqual(AppModule.objects.count(), len(DEFAULT_MODULES))
        self.assertEqual(Account.objects.count(), len(DEFAULT_ACCOUNTS))

    def test_init_modules_command_creates_missing_modules_and_is_idempotent(self):
        from io import StringIO
        from django.core.management import call_command
        from core.models.settings_models import DEFAULT_MODULES

        AppModule.objects.all().delete()

        out = StringIO()
        call_command('init_modules', stdout=out)
        self.assertEqual(AppModule.objects.count(), len(DEFAULT_MODULES))
        self.assertIn(f"{len(DEFAULT_MODULES)} créé(s)", out.getvalue())

        out = StringIO()
        call_command('init_modules', stdout=out)
        self.assertEqual(AppModule.objects.count(), len(DEFAULT_MODULES))
        self.assertIn("0 créé(s)", out.getvalue())

    def test_init_modules_update_realigns_existing_modules(self):
        from io import StringIO
        from django.core.management import call_command

        module = AppModule.objects.get(code='sales')
        module.name = 'Nom modifié'
        module.icon = ''
        module.order = 99
        module.is_active = False
        module.save()

        # Sans --update : rien ne change
        call_command('init_modules', stdout=StringIO())
        module.refresh_from_db()
        self.assertEqual(module.name, 'Nom modifié')

        out = StringIO()
        call_command('init_modules', '--update', stdout=out)
        module.refresh_from_db()
        self.assertEqual(module.name, 'Ventes')
        self.assertEqual(module.icon, '🛒')
        self.assertEqual(module.order, 2)
        self.assertFalse(module.is_active)  # is_active est conservé
        self.assertIn("1 mis à jour", out.getvalue())

    def test_init_accounts_command_creates_chart_of_accounts(self):
        from io import StringIO
        from django.core.management import call_command
        from core.services.accounting_service import DEFAULT_ACCOUNTS
        from core.models import Account

        Account.objects.all().delete()

        out = StringIO()
        call_command('init_accounts', stdout=out)
        self.assertEqual(Account.objects.count(), len(DEFAULT_ACCOUNTS))
        self.assertIn(f"{len(DEFAULT_ACCOUNTS)} compte(s) créé(s)", out.getvalue())

        # Idempotent
        call_command('init_accounts', stdout=StringIO())
        self.assertEqual(Account.objects.count(), len(DEFAULT_ACCOUNTS))


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class InternationalizationTests(TestCase):
    """Interface bilingue français / anglais : sélecteur de langue, catalogues et API."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from io import StringIO
        from django.core.management import call_command
        from django.utils.translation import trans_real

        # Les .mo ne sont pas versionnés : on les compile depuis les .po (idempotent)
        call_command('translations', 'compile', stdout=StringIO())
        trans_real._translations.clear()
        trans_real._default = None

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='admin-i18n', email='admin-i18n@example.com', password='password123',
        )

    def _english(self, msgid, domain='django'):
        """Traduction anglaise attendue, lue dans le .po (évite de figer le texte dans le test)."""
        from django.conf import settings
        from babel.messages.pofile import read_po
        path = f"{settings.LOCALE_PATHS[0]}/en/LC_MESSAGES/{domain}.po"
        with open(path, 'rb') as fh:
            catalog = read_po(fh)
        message = catalog.get(msgid)
        self.assertIsNotNone(message, f"msgid absent du catalogue {domain} : {msgid!r}")
        self.assertTrue(message.string, f"msgid non traduit : {msgid!r}")
        return message.string

    def test_default_language_is_french(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Language'], 'fr')
        self.assertContains(response, 'Déconnexion')
        self.assertContains(response, '<html lang="fr">')

    def test_set_language_cookie_switches_to_english(self):
        from django.conf import settings
        self.client.force_login(self.user)
        response = self.client.post(reverse('set_language'), {'language': 'en', 'next': '/'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.cookies[settings.LANGUAGE_COOKIE_NAME].value, 'en')

        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response['Content-Language'], 'en')
        self.assertContains(response, '<html lang="en">')
        self.assertContains(response, self._english('Déconnexion'))
        self.assertNotContains(response, 'Déconnexion')
        # Le sélecteur marque la langue active
        self.assertContains(response, 'class="lang-btn active"', count=1)

    def test_accept_language_header_is_honoured_on_login_page(self):
        response = self.client.get(reverse('login'), HTTP_ACCEPT_LANGUAGE='en')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Language'], 'en')
        self.assertContains(response, '<html lang="en">')

    def test_javascript_catalog_is_localized(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('javascript-catalog'), HTTP_ACCEPT_LANGUAGE='en')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('django.catalog', body)
        self.assertIn(json.dumps(self._english('Le panier est vide', domain='djangojs')), body)

    def test_api_error_messages_follow_accept_language(self):
        url = '/api/auth/login/'
        payload = {'username': 'admin-i18n', 'password': 'mauvais'}
        fr = self.client.post(url, payload, HTTP_ACCEPT_LANGUAGE='fr').json()
        en = self.client.post(url, payload, HTTP_ACCEPT_LANGUAGE='en').json()
        self.assertEqual(fr['errors']['non_field_errors'], ['Identifiants invalides.'])
        self.assertEqual(en['errors']['non_field_errors'], [self._english('Identifiants invalides.')])

    def test_seeded_reference_names_are_translated_at_render_time(self):
        from django.utils.translation import gettext, override
        from core.models import Account
        AccountingService.init_chart_of_accounts()
        AppModule.init_default_modules()
        account = Account.objects.get(code='701')
        module = AppModule.objects.get(code='dashboard')
        with override('en'):
            self.assertEqual(gettext(account.name), self._english(account.name))
            self.assertIn(self._english(module.name), str(module))  # __str__ = icône + nom traduit
        with override('fr'):
            self.assertEqual(gettext(account.name), account.name)

    def test_catalogs_are_complete_and_well_formed(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('translations', 'check', stdout=out)
        self.assertIn('Toutes les traductions sont complètes', out.getvalue(), out.getvalue())


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class SettingsPageTests(TestCase):
    """La page Paramètres doit permettre d'éditer le singleton SystemSettings depuis le web."""

    def setUp(self):
        AppModule.init_default_modules()
        self.user = get_user_model().objects.create_superuser(
            username='admin-settings',
            email='admin-settings@example.com',
            password='password123',
        )
        self.user.firstname = 'Admin'
        self.user.lastname = 'Réglages'
        self.user.role = 'Administrateur'
        self.user.gender = 'M'
        self.user.save()
        self.client.force_login(self.user)

    def test_get_settings_page_shows_current_values(self):
        settings_obj = SystemSettings.get_settings()
        settings_obj.company_name = 'Boutique Test'
        settings_obj.save()

        response = self.client.get(reverse('settings'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Boutique Test')

    def test_post_settings_page_updates_singleton(self):
        response = self.client.post(reverse('settings'), {
            'company_name': 'Nouvelle Boutique',
            'company_address': 'Douala',
            'company_phone': '699000000',
            'company_email': 'contact@example.com',
            'company_website': '',
            'tax_id': 'NIF-123',
            'trade_register': 'RC-456',
            'currency_symbol': 'FCFA',
            'currency_code': 'XAF',
            'receipt_header': '',
            'receipt_footer': 'Merci !',
            'low_stock_threshold': 5,
            'tva_accounting_mode': 'IMMEDIATE',
        })

        self.assertRedirects(response, reverse('settings'))
        settings_obj = SystemSettings.get_settings()
        self.assertEqual(settings_obj.company_name, 'Nouvelle Boutique')
        self.assertEqual(settings_obj.low_stock_threshold, 5)
        self.assertFalse(settings_obj.enable_tva_accounting)  # case à cocher absente du POST


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class ProductCrudPagesTests(TestCase):
    """CRUD produit et données de référence (catégories/gammes/rayons/grammages) depuis le web."""

    def setUp(self):
        AppModule.init_default_modules()
        self.user = get_user_model().objects.create_superuser(
            username='admin-products',
            email='admin-products@example.com',
            password='password123',
        )
        self.user.firstname = 'Admin'
        self.user.lastname = 'Produits'
        self.user.role = 'Administrateur'
        self.user.gender = 'M'
        self.user.save()
        self.client.force_login(self.user)
        self.category = Category.objects.create(name='Boissons')

    def test_add_product_creates_product_and_initial_supply(self):
        response = self.client.post(reverse('add_product'), {
            'code': 'PRD-NEW-001',
            'name': 'Jus de mangue',
            'description': '',
            'brand': 'Blanco',
            'color': '',
            'stock': 20,
            'stock_limit': 5,
            'max_salable_price': '2000',
            'last_purchase_price': '1200',
            'actual_price': '1500',
            'exp_alert_period': '',
            'grammage': '',
            'category': self.category.pk,
        })

        product = Product.objects.get(code='PRD-NEW-001')
        self.assertRedirects(response, reverse('product_detail', kwargs={'pk': product.pk}))
        self.assertEqual(product.stock, 20)
        self.assertTrue(Supply.objects.filter(product=product).exists())

    def test_add_product_rejects_duplicate_code(self):
        Product.objects.create(code='PRD-DUP', name='Existant', stock=1)

        response = self.client.post(reverse('add_product'), {
            'code': 'PRD-DUP',
            'name': 'Doublon',
            'stock': 0,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ce code produit est déjà utilisé.')

    def test_edit_product_does_not_change_stock(self):
        product = Product.objects.create(code='PRD-EDIT', name='Ancien nom', stock=7, actual_price=1000)

        response = self.client.post(reverse('edit_product', kwargs={'pk': product.pk}), {
            'code': 'PRD-EDIT',
            'name': 'Nouveau nom',
            'description': '',
            'brand': '',
            'color': '',
            'stock_limit': '',
            'max_salable_price': '',
            'last_purchase_price': '',
            'actual_price': '1200',
            'exp_alert_period': '',
            'grammage': '',
        })

        self.assertRedirects(response, reverse('product_detail', kwargs={'pk': product.pk}))
        product.refresh_from_db()
        self.assertEqual(product.name, 'Nouveau nom')
        self.assertEqual(product.stock, 7)  # inchangé : le stock ne passe pas par ce formulaire
        self.assertEqual(product.actual_price, Decimal('1200'))

    def test_edit_product_rejects_min_price_above_selling_price(self):
        product = Product.objects.create(code='PRD-MIN', name='Produit', stock=1, actual_price=1000)

        response = self.client.post(reverse('edit_product', kwargs={'pk': product.pk}), {
            'code': 'PRD-MIN',
            'name': 'Produit',
            'description': '',
            'brand': '',
            'color': '',
            'stock_limit': '',
            'min_salable_price': '1000',
            'max_salable_price': '',
            'last_purchase_price': '',
            'actual_price': '1000',
            'exp_alert_period': '',
            'grammage': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Le prix minimum doit être inférieur au prix de vente du produit.')
        product.refresh_from_db()
        self.assertIsNone(product.min_salable_price)

    def test_edit_product_rejects_max_price_below_selling_price(self):
        product = Product.objects.create(code='PRD-MAX', name='Produit', stock=1, actual_price=1000)

        response = self.client.post(reverse('edit_product', kwargs={'pk': product.pk}), {
            'code': 'PRD-MAX',
            'name': 'Produit',
            'description': '',
            'brand': '',
            'color': '',
            'stock_limit': '',
            'min_salable_price': '',
            'max_salable_price': '900',
            'last_purchase_price': '',
            'actual_price': '1000',
            'exp_alert_period': '',
            'grammage': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Le prix maximum doit être supérieur au prix de vente du produit.')
        product.refresh_from_db()
        self.assertIsNone(product.max_salable_price)

    def test_edit_product_accepts_valid_min_and_max_price(self):
        product = Product.objects.create(code='PRD-VALID', name='Produit', stock=1, actual_price=1000)

        response = self.client.post(reverse('edit_product', kwargs={'pk': product.pk}), {
            'code': 'PRD-VALID',
            'name': 'Produit',
            'description': '',
            'brand': '',
            'color': '',
            'stock_limit': '',
            'min_salable_price': '800',
            'max_salable_price': '1200',
            'last_purchase_price': '',
            'actual_price': '1000',
            'exp_alert_period': '',
            'grammage': '',
        })

        self.assertRedirects(response, reverse('product_detail', kwargs={'pk': product.pk}))
        product.refresh_from_db()
        self.assertEqual(product.min_salable_price, Decimal('800'))
        self.assertEqual(product.max_salable_price, Decimal('1200'))

    def test_delete_product_soft_deletes(self):
        product = Product.objects.create(code='PRD-DEL', name='À désactiver', stock=3)

        response = self.client.post(reverse('delete_product', kwargs={'pk': product.pk}))

        self.assertRedirects(response, reverse('products'))
        product.refresh_from_db()
        self.assertIsNotNone(product.delete_at)

    def test_category_crud_via_web(self):
        # Création
        response = self.client.post(reverse('add_reference', kwargs={'kind': 'categories'}), {
            'name': 'Épicerie',
            'description': 'Produits secs',
        })
        category = Category.objects.get(name='Épicerie')
        self.assertRedirects(response, reverse('product_references') + '?tab=categories')

        # Modification
        response = self.client.post(reverse('edit_reference', kwargs={'kind': 'categories', 'pk': category.pk}), {
            'name': 'Épicerie salée',
            'description': '',
        })
        category.refresh_from_db()
        self.assertEqual(category.name, 'Épicerie salée')

        # Désactivation (soft-delete)
        response = self.client.post(reverse('delete_reference', kwargs={'kind': 'categories', 'pk': category.pk}))
        category.refresh_from_db()
        self.assertIsNotNone(category.delete_at)

    def test_reference_delete_blocked_when_products_attached(self):
        gamme = Gamme.objects.create(name='Gamme liée')
        Product.objects.create(code='PRD-GAMME', name='Produit lié', stock=1, gamme=gamme)

        self.client.post(reverse('delete_reference', kwargs={'kind': 'gammes', 'pk': gamme.pk}))

        gamme.refresh_from_db()
        self.assertIsNone(gamme.delete_at)


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class StaffManagementPagesTests(TestCase):
    """Gestion du personnel depuis le web : création, modification, statut, mot de passe."""

    def setUp(self):
        AppModule.init_default_modules()
        self.sales_module = AppModule.objects.get(code='sales')
        self.admin = get_user_model().objects.create_superuser(
            username='admin-staff',
            email='admin-staff@example.com',
            password='password123',
        )
        self.admin.firstname = 'Admin'
        self.admin.lastname = 'Personnel'
        self.admin.role = 'Administrateur'
        self.admin.gender = 'M'
        self.admin.save()
        self.client.force_login(self.admin)

    def _base_payload(self, **overrides):
        payload = {
            'username': 'caissiere1',
            'firstname': 'Marie',
            'lastname': 'Kaffo',
            'email': 'marie@example.com',
            'phone_number': '699000000',
            'role': 'Caissière',
            'gender': 'F',
            'allowed_modules': [self.sales_module.pk],
        }
        payload.update(overrides)
        return payload

    def test_add_staff_creates_active_account_with_modules(self):
        response = self.client.post(reverse('add_staff'), self._base_payload(
            password1='MotDePasse!2026',
            password2='MotDePasse!2026',
        ))

        self.assertRedirects(response, reverse('contacts') + '?tab=staff')
        user = get_user_model().objects.get(username='caissiere1')
        self.assertTrue(user.check_password('MotDePasse!2026'))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_superuser)
        self.assertIn(self.sales_module, user.allowed_modules.all())

    def test_add_staff_rejects_mismatched_passwords(self):
        response = self.client.post(reverse('add_staff'), self._base_payload(
            password1='MotDePasse!2026',
            password2='Autre!2026',
        ))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username='caissiere1').exists())

    def test_add_staff_forbidden_for_non_superuser(self):
        simple_user = get_user_model().objects.create_user(
            username='simple', email='simple@example.com', password='password123',
        )
        simple_user.allowed_modules.add(AppModule.objects.get(code='contacts'))
        self.client.force_login(simple_user)

        response = self.client.get(reverse('add_staff'))

        self.assertEqual(response.status_code, 403)

    def test_edit_staff_updates_role_and_modules(self):
        staff_member = get_user_model().objects.create_user(
            username='caissiere2', email='c2@example.com', password='password123',
            firstname='Awa', lastname='Nkeng', role='Caissière',
        )

        response = self.client.post(reverse('edit_staff', kwargs={'pk': staff_member.pk}), self._base_payload(
            username='caissiere2', role='Superviseuse',
        ))

        self.assertRedirects(response, reverse('contacts') + '?tab=staff')
        staff_member.refresh_from_db()
        self.assertEqual(staff_member.role, 'Superviseuse')
        self.assertIn(self.sales_module, staff_member.allowed_modules.all())

    def test_edit_staff_cannot_strip_last_superuser(self):
        response = self.client.post(reverse('edit_staff', kwargs={'pk': self.admin.pk}), self._base_payload(
            username='admin-staff',
        ))  # is_superuser/is_active absents du payload -> tentative de retrait

        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser)
        self.assertTrue(self.admin.is_active)

    def test_toggle_staff_active_deactivates_and_reactivates(self):
        staff_member = get_user_model().objects.create_user(
            username='caissiere3', email='c3@example.com', password='password123',
        )

        self.client.post(reverse('toggle_staff_active', kwargs={'pk': staff_member.pk}))
        staff_member.refresh_from_db()
        self.assertFalse(staff_member.is_active)

        self.client.post(reverse('toggle_staff_active', kwargs={'pk': staff_member.pk}))
        staff_member.refresh_from_db()
        self.assertTrue(staff_member.is_active)

    def test_toggle_staff_active_blocks_last_superuser(self):
        response = self.client.post(reverse('toggle_staff_active', kwargs={'pk': self.admin.pk}))

        self.assertRedirects(response, reverse('contacts') + '?tab=staff')
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_reset_staff_password_sets_new_password_and_revokes_tokens(self):
        from rest_framework.authtoken.models import Token

        staff_member = get_user_model().objects.create_user(
            username='caissiere4', email='c4@example.com', password='ancien-mdp',
        )
        Token.objects.create(user=staff_member)

        response = self.client.post(
            reverse('reset_staff_password', kwargs={'pk': staff_member.pk}),
            {'new_password1': 'NouveauMdp!2026', 'new_password2': 'NouveauMdp!2026'},
        )

        self.assertRedirects(response, reverse('contacts') + '?tab=staff')
        staff_member.refresh_from_db()
        self.assertTrue(staff_member.check_password('NouveauMdp!2026'))
        self.assertFalse(Token.objects.filter(user=staff_member).exists())


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class ClientSupplierDeactivationTests(TestCase):
    """Désactivation (soft-delete) de clients et fournisseurs, bloquée sur créance/dette en cours."""

    def setUp(self):
        AppModule.init_default_modules()
        self.user = get_user_model().objects.create_superuser(
            username='admin-contacts',
            email='admin-contacts@example.com',
            password='password123',
        )
        self.user.firstname = 'Admin'
        self.user.lastname = 'Contacts'
        self.user.gender = 'M'
        self.user.save()
        self.client.force_login(self.user)
        now = timezone.now()
        self.exercise = Exercise.objects.create(start_date=now)
        self.daily = Daily.objects.create(start_date=now, exercise=self.exercise)

    def test_delete_client_without_credit_deactivates(self):
        customer = Client.objects.create(firstname='Awa', lastname='Nkeng', phone_number='690000000')

        response = self.client.post(reverse('delete_client', kwargs={'pk': customer.pk}))

        self.assertRedirects(response, reverse('contacts') + '?tab=clients')
        customer.refresh_from_db()
        self.assertIsNotNone(customer.delete_at)

    def test_delete_client_blocked_with_outstanding_credit(self):
        customer = Client.objects.create(firstname='Fatou', lastname='Bello', phone_number='690000001')
        sale = Sale.objects.create(daily=self.daily, client=customer, total=Decimal('5000'), is_credit=True)
        CreditSale.objects.create(sale=sale, amount_paid=Decimal('0'), amount_remaining=Decimal('5000'), is_fully_paid=False)

        response = self.client.post(reverse('delete_client', kwargs={'pk': customer.pk}))

        self.assertRedirects(response, reverse('contacts') + '?tab=clients')
        customer.refresh_from_db()
        self.assertIsNone(customer.delete_at)

    def test_delete_supplier_without_debt_deactivates(self):
        supplier = Supplier.objects.create(name='Fournisseur Test')

        response = self.client.post(reverse('delete_supplier', kwargs={'pk': supplier.pk}))

        self.assertRedirects(response, reverse('suppliers'))
        supplier.refresh_from_db()
        self.assertIsNotNone(supplier.delete_at)

    def test_delete_supplier_blocked_with_outstanding_debt(self):
        supplier = Supplier.objects.create(name='Fournisseur Endetté')
        product = Product.objects.create(code='PRD-CRED-SUP', name='Produit crédit fournisseur', stock=5)
        supply = Supply.objects.create(
            product=product, supplier=supplier, daily=self.daily,
            quantity=5, purchase_cost=Decimal('1000'), total_price=Decimal('5000'), is_credit=True, is_paid=False,
        )
        CreditSupply.objects.create(supply=supply, amount_paid=Decimal('0'), amount_remaining=Decimal('5000'), is_fully_paid=False)

        response = self.client.post(reverse('delete_supplier', kwargs={'pk': supplier.pk}))

        self.assertRedirects(response, reverse('suppliers'))
        supplier.refresh_from_db()
        self.assertIsNone(supplier.delete_at)


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class AlertsBadgeTests(TestCase):
    """Cloche de notifications : compteurs de stock bas et d'échéances en retard."""

    def setUp(self):
        AppModule.init_default_modules()
        self.user = get_user_model().objects.create_superuser(
            username='admin-alerts',
            email='admin-alerts@example.com',
            password='password123',
        )
        self.user.gender = 'M'
        self.user.save()
        self.client.force_login(self.user)

    def test_dashboard_shows_no_badge_without_alerts(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['alert_total_count'], 0)
        self.assertNotContains(response, 'alerts-badge')

    def test_dashboard_shows_low_stock_badge(self):
        Product.objects.create(code='PRD-LOW', name='Stock bas', stock=1, stock_limit=5)

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.context['alert_low_stock_count'], 1)
        self.assertContains(response, 'alerts-badge')

    def test_dashboard_shows_overdue_payment_badge(self):
        now = timezone.now()
        exercise = Exercise.objects.create(start_date=now)
        daily = Daily.objects.create(start_date=now, exercise=exercise)
        customer = Client.objects.create(firstname='Awa', lastname='Nkeng')
        sale = Sale.objects.create(daily=daily, client=customer, total=Decimal('1000'), is_credit=True)
        credit_sale = CreditSale.objects.create(sale=sale, amount_paid=Decimal('0'), amount_remaining=Decimal('1000'))
        PaymentSchedule.objects.create(
            schedule_type='CLIENT', credit_sale=credit_sale,
            due_date=timezone.localdate() - timedelta(days=3),
            amount_due=Decimal('1000'), status='PENDING',
        )

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.context['alert_overdue_payments_count'], 1)
        self.assertContains(response, 'alerts-badge')

    def test_alerts_hidden_for_user_without_module_access(self):
        simple_user = get_user_model().objects.create_user(
            username='caisse-alerts', email='caisse-alerts@example.com', password='password123',
        )
        simple_user.allowed_modules.add(AppModule.objects.get(code='dashboard'))
        Product.objects.create(code='PRD-LOW2', name='Stock bas 2', stock=1, stock_limit=5)
        self.client.force_login(simple_user)

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.context['alert_low_stock_count'], 0)


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class ProductBulkImportExportTests(TestCase):
    """Export CSV du catalogue et mise à jour de prix en masse par réimport."""

    def setUp(self):
        AppModule.init_default_modules()
        self.user = get_user_model().objects.create_superuser(
            username='admin-bulk',
            email='admin-bulk@example.com',
            password='password123',
        )
        self.user.gender = 'M'
        self.user.save()
        self.client.force_login(self.user)

    def test_export_contains_product_rows(self):
        Product.objects.create(code='PRD-EXP', name='Produit export', stock=3, actual_price=Decimal('1000'))

        response = self.client.get(reverse('export_products_csv'))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8-sig')
        self.assertIn('PRD-EXP', content)

    def test_import_updates_price_by_code_without_touching_stock(self):
        product = Product.objects.create(
            code='PRD-IMP', name='Produit import', stock=7,
            actual_price=Decimal('1000'), max_salable_price=Decimal('1500'),
        )
        csv_content = (
            "Code;Nom;Catégorie;Gamme;Rayon;Type de grammage;Stock;Seuil de stock;"
            "Prix actuel;Prix maximum;Prix d'achat;TVA applicable;Prix réductible\r\n"
            "PRD-IMP;Produit import;;;;;7;5;1200;1800;900;Oui;Non\r\n"
        ).encode('utf-8-sig')
        upload = SimpleUploadedFile('catalogue.csv', csv_content, content_type='text/csv')

        response = self.client.post(reverse('import_products_csv'), {'file': upload})

        self.assertRedirects(response, reverse('products'))
        product.refresh_from_db()
        self.assertEqual(product.stock, 7)  # inchangé : le stock n'est jamais importé
        self.assertEqual(product.actual_price, Decimal('1200'))
        self.assertEqual(product.max_salable_price, Decimal('1800'))
        self.assertEqual(product.stock_limit, 5)
        self.assertFalse(product.is_price_reducible)

    def test_import_reports_unknown_code_without_creating_product(self):
        csv_content = (
            "Code;Nom;Catégorie;Gamme;Rayon;Type de grammage;Stock;Seuil de stock;"
            "Prix actuel;Prix maximum;Prix d'achat;TVA applicable;Prix réductible\r\n"
            "PRD-INCONNU;X;;;;;0;;1000;;;;\r\n"
        ).encode('utf-8-sig')
        upload = SimpleUploadedFile('catalogue.csv', csv_content, content_type='text/csv')

        response = self.client.post(reverse('import_products_csv'), {'file': upload})

        self.assertRedirects(response, reverse('products'))
        self.assertFalse(Product.objects.filter(code='PRD-INCONNU').exists())


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class PurchaseOrderWorkflowTests(TestCase):
    """
    Commande fournisseur (PurchaseOrder) distincte de la réception (Supply) :
    la commande ne doit avoir aucun effet sur le stock ni la comptabilité
    tant qu'elle n'est pas réceptionnée.
    """

    def setUp(self):
        AppModule.init_default_modules()
        self.user = get_user_model().objects.create_superuser(
            username='admin-po',
            email='admin-po@example.com',
            password='password123',
        )
        self.user.gender = 'M'
        self.user.save()
        self.client.force_login(self.user)

        AccountingService.init_chart_of_accounts()
        self.supplier = Supplier.objects.create(name='Fournisseur PO')
        self.product = Product.objects.create(
            code='PRD-PO', name='Produit commandé', stock=5, has_vat=False,
        )

    def test_create_purchase_order_has_no_stock_or_accounting_effect(self):
        self.assertEqual(self.client.get(reverse('add_purchase_order')).status_code, 200)
        self.assertEqual(self.client.get(reverse('purchase_orders')).status_code, 200)

        response = self.client.post(reverse('add_purchase_order'), {
            'product': self.product.pk,
            'supplier': self.supplier.pk,
            'quantity': 20,
            'purchase_cost': '1000',
        })

        self.assertRedirects(response, reverse('purchase_orders'))
        order = PurchaseOrder.objects.get(product=self.product)
        self.assertEqual(order.status, 'ORDERED')
        self.assertEqual(order.quantity, 20)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)  # inchangé : rien n'est reçu
        self.assertFalse(Supply.objects.filter(product=self.product).exists())
        self.assertFalse(JournalEntry.objects.exists())

    def test_receive_purchase_order_creates_supply_updates_stock_and_accounting(self):
        order = PurchaseOrder.objects.create(
            product=self.product, supplier=self.supplier, staff=self.user,
            daily=Daily.objects.create(start_date=timezone.now(), exercise=Exercise.objects.create(start_date=timezone.now())),
            quantity=10, estimated_purchase_cost=Decimal('900'), status='ORDERED',
        )

        self.assertEqual(self.client.get(reverse('receive_purchase_order', kwargs={'pk': order.pk})).status_code, 200)

        response = self.client.post(reverse('receive_purchase_order', kwargs={'pk': order.pk}), {
            'purchase_cost': '950',
            'payment_method': 'CASH',
        })

        self.assertRedirects(response, reverse('supplies'))
        order.refresh_from_db()
        self.assertEqual(order.status, 'RECEIVED')
        self.assertIsNotNone(order.supply)

        supply = order.supply
        self.assertEqual(supply.quantity, 10)
        self.assertEqual(supply.purchase_cost, Decimal('950'))
        self.assertEqual(supply.total_price, Decimal('9500'))

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 15)  # 5 initial + 10 reçus
        self.assertEqual(self.product.last_purchase_price, Decimal('950'))
        self.assertTrue(JournalEntry.objects.filter(supply=supply).exists())

    def test_cancel_purchase_order_before_receipt_has_no_stock_effect(self):
        order = PurchaseOrder.objects.create(
            product=self.product, supplier=self.supplier, staff=self.user,
            daily=Daily.objects.create(start_date=timezone.now(), exercise=Exercise.objects.create(start_date=timezone.now())),
            quantity=10, estimated_purchase_cost=Decimal('900'), status='ORDERED',
        )

        response = self.client.post(reverse('cancel_purchase_order', kwargs={'pk': order.pk}))

        self.assertRedirects(response, reverse('purchase_orders'))
        order.refresh_from_db()
        self.assertIsNotNone(order.delete_at)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)

    def test_cannot_receive_a_cancelled_order(self):
        order = PurchaseOrder.objects.create(
            product=self.product, supplier=self.supplier, staff=self.user,
            daily=Daily.objects.create(start_date=timezone.now(), exercise=Exercise.objects.create(start_date=timezone.now())),
            quantity=10, estimated_purchase_cost=Decimal('900'), status='ORDERED',
        )
        SupplyService.cancel_purchase_order(order)

        response = self.client.get(reverse('receive_purchase_order', kwargs={'pk': order.pk}))

        self.assertEqual(response.status_code, 404)


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class InvoicePdfTests(TestCase):
    """Téléchargement de facture au format PDF."""

    def setUp(self):
        AppModule.init_default_modules()
        self.user = get_user_model().objects.create_superuser(
            username='admin-invoices',
            email='admin-invoices@example.com',
            password='password123',
        )
        self.user.gender = 'M'
        self.user.save()
        self.client.force_login(self.user)

        now = timezone.now()
        exercise = Exercise.objects.create(start_date=now)
        daily = Daily.objects.create(start_date=now, exercise=exercise)
        customer = Client.objects.create(firstname='Awa', lastname='Nkeng', phone_number='690000000')
        product = Product.objects.create(code='PRD-PDF', name='Produit facturé', stock=5, actual_price=Decimal('2000'))
        self.sale = Sale.objects.create(daily=daily, client=customer, total=Decimal('2000'), is_paid=True)
        SaleProduct.objects.create(sale=self.sale, product=product, quantity=1, unit_price=Decimal('2000'))
        self.invoice = Invoice.objects.create(
            sale=self.sale,
            invoice_number='FAC-TEST-PDF-001',
            invoice_date=timezone.localdate(),
            status='PAID',
        )

    def test_invoice_pdf_downloads_valid_pdf(self):
        response = self.client.get(reverse('invoice_pdf', kwargs={'pk': self.invoice.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('FAC-TEST-PDF-001', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))


class CreditSaleRequiresClientTests(TestCase):
    """Une vente à crédit doit être rattachée à un client identifié."""

    def setUp(self):
        AppModule.init_default_modules()
        self.user = get_user_model().objects.create_superuser(
            username='admin-credit-client',
            email='admin-credit-client@example.com',
            password='password123',
        )
        self.user.gender = 'M'
        self.user.save()

        now = timezone.now()
        exercise = Exercise.objects.create(start_date=now)
        Daily.objects.create(start_date=now, exercise=exercise)
        self.product = Product.objects.create(
            code='PRD-CREDIT-NOCLIENT', name='Produit', stock=5, actual_price=Decimal('1000'),
        )
        self.customer = Client.objects.create(firstname='Fatou', lastname='Bello', phone_number='690000222')

    def test_create_sale_rejects_credit_without_client(self):
        with self.assertRaises(ValueError):
            SaleService.create_sale(
                validated_data={
                    'is_credit': True,
                    'due_date': timezone.localdate() + timedelta(days=7),
                    'items': [{'product_id': self.product.id, 'quantity': 1, 'unit_price': Decimal('1000')}],
                },
                staff=self.user,
            )
        self.assertEqual(Sale.objects.count(), 0)

    def test_create_sale_accepts_credit_with_client(self):
        sale = SaleService.create_sale(
            validated_data={
                'client_id': self.customer.id,
                'is_credit': True,
                'due_date': timezone.localdate() + timedelta(days=7),
                'items': [{'product_id': self.product.id, 'quantity': 1, 'unit_price': Decimal('1000')}],
            },
            staff=self.user,
        )
        self.assertEqual(sale.client_id, self.customer.id)
        self.assertTrue(sale.is_credit)

    def test_serializer_rejects_credit_without_client_id(self):
        serializer = SaleCreateSerializer(data={
            'is_credit': True,
            'due_date': str(timezone.localdate() + timedelta(days=7)),
            'items': [{'product_id': self.product.id, 'quantity': 1, 'unit_price': '1000'}],
        })

        self.assertFalse(serializer.is_valid())
        self.assertIn('client_id', serializer.errors)


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class AddClientAjaxPopupTests(TestCase):
    """Raccourci « + » d'ajout de client (popup) depuis la page Ventes."""

    def setUp(self):
        AppModule.init_default_modules()
        self.user = get_user_model().objects.create_superuser(
            username='admin-add-client-ajax',
            email='admin-add-client-ajax@example.com',
            password='password123',
        )
        self.user.gender = 'M'
        self.user.save()
        self.client.force_login(self.user)

    def test_ajax_creates_client_and_returns_json(self):
        response = self.client.post(
            reverse('add_client'),
            {'firstname': 'Aïcha', 'lastname': 'Mballa', 'phone_number': '690000333'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        client = Client.objects.get(pk=data['id'])
        self.assertEqual(data['name'], str(client))
        self.assertEqual(client.firstname, 'Aïcha')

    def test_ajax_returns_field_errors_without_creating_client(self):
        response = self.client.post(
            reverse('add_client'),
            {'firstname': '', 'lastname': 'Mballa'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('firstname', data['errors'])
        self.assertFalse(Client.objects.filter(lastname='Mballa').exists())

    def test_non_ajax_post_still_redirects_to_contacts(self):
        response = self.client.post(
            reverse('add_client'),
            {'firstname': 'Paul', 'lastname': 'Eto'},
        )

        self.assertRedirects(response, reverse('contacts'))
        self.assertTrue(Client.objects.filter(firstname='Paul', lastname='Eto').exists())
