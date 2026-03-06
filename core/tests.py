from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Product


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class ProductPagesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='password123',
        )
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
