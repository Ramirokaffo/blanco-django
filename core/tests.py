from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import AppModule, Product


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
        self.assertContains(response, reverse('personnel_statistics'))

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