from rest_framework import serializers
from .models import Product, Sale, SaleProduct, Client


class ProductSearchSerializer(serializers.ModelSerializer):
    """Serializer pour la recherche de produits"""

    class Meta:
        model = Product
        fields = ['id', 'code', 'name', 'stock', 'max_salable_price', "actual_price", "is_price_reducible"]
    
    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Ajouter des informations supplémentaires
        data['available'] = instance.stock > 0
        return data


class SaleItemSerializer(serializers.Serializer):
    """Serializer pour les articles d'une vente"""
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2)

    def validate_product_id(self, value):
        """Vérifier que le produit existe"""
        try:
            Product.objects.get(id=value)
        except Product.DoesNotExist:
            raise serializers.ValidationError("Produit introuvable")
        return value

    def validate(self, data):
        """Validation globale de l'article"""
        product = Product.objects.get(id=data['product_id'])

        # Vérifier le stock
        if data['quantity'] > product.stock:
            raise serializers.ValidationError({
                'quantity': f"Stock insuffisant. Stock disponible: {product.stock}"
            })

        # Vérifier que le prix ne dépasse pas le prix max
        if product.max_salable_price and data['unit_price'] > product.max_salable_price:
            raise serializers.ValidationError({
                'unit_price': f"Prix trop élevé. Prix maximum: {product.max_salable_price}"
            })

        # Vérifier que si le prix est réduit, le produit doit être réductible
        if data['unit_price'] < product.actual_price and not product.is_price_reducible:
            raise serializers.ValidationError({
                'unit_price': "Le prix de ce produit ne peut pas être réduit"
            })

        return data


class SaleCreateSerializer(serializers.Serializer):
    """Serializer pour créer une vente"""
    client_id = serializers.IntegerField(required=False, allow_null=True)
    is_credit = serializers.BooleanField(default=False)
    due_date = serializers.DateField(required=False, allow_null=True)
    items = SaleItemSerializer(many=True)
    
    def validate_client_id(self, value):
        """Vérifier que le client existe"""
        if value:
            try:
                Client.objects.get(id=value)
            except Client.DoesNotExist:
                raise serializers.ValidationError("Client introuvable")
        return value
    
    def validate(self, data):
        """Validation globale de la vente"""
        # Si c'est une vente à crédit, la date d'échéance est obligatoire
        if data.get('is_credit') and not data.get('due_date'):
            raise serializers.ValidationError({
                'due_date': "La date d'échéance est obligatoire pour une vente à crédit"
            })
        
        # Vérifier qu'il y a au moins un article
        if not data.get('items'):
            raise serializers.ValidationError({
                'items': "La vente doit contenir au moins un article"
            })
        
        return data
    
    def create(self, validated_data):
        """Créer la vente et ses articles"""
        items_data = validated_data.pop('items')

        # Récupérer le staff (utilisateur connecté)
        # Maintenant request.user est directement un CustomUser (Staff)
        request = self.context.get('request')
        staff = request.user

        # Récupérer le client si spécifié
        client_id = validated_data.pop('client_id', None)
        client = Client.objects.get(id=client_id) if client_id else None

        # Récupérer les informations de crédit
        is_credit = validated_data.get('is_credit', False)
        due_date = validated_data.get('due_date')

        # Calculer le total
        total = sum(
            item['unit_price'] * item['quantity']
            for item in items_data
        )

        # Récupérer la session Daily ouverte
        from .models import Daily

        # Chercher une session Daily ouverte (sans end_date)
        daily = Daily.objects.filter(end_date__isnull=True).first()

        if not daily:
            raise serializers.ValidationError(
                "Aucune session Daily ouverte. Veuillez créer une session Daily avant de créer une vente."
            )

        # Créer la vente
        sale = Sale.objects.create(
            client=client,
            staff=staff,
            daily=daily,
            total=total,
            is_credit=is_credit,
            is_paid=not is_credit  # Payé si comptant, non payé si crédit
        )
        
        # Créer les articles de vente et mettre à jour le stock
        for item_data in items_data:
            product = Product.objects.get(id=item_data['product_id'])

            # Créer l'article de vente
            SaleProduct.objects.create(
                sale=sale,
                product=product,
                quantity=item_data['quantity'],
                unit_price=item_data['unit_price'],
            )

            # Mettre à jour le stock
            product.stock -= item_data['quantity']
            product.save()

        # Si c'est une vente à crédit, créer l'enregistrement CreditSale
        if is_credit:
            from .models import CreditSale
            CreditSale.objects.create(
                sale=sale,
                amount_paid=0,
                amount_remaining=total,
                due_date=due_date,
                is_fully_paid=False
            )

        return sale


class SaleSerializer(serializers.ModelSerializer):
    """Serializer pour afficher une vente"""
    client_name = serializers.SerializerMethodField()
    staff_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Sale
        fields = ['id', 'client_name', 'staff_name', 'total', 'is_credit', 
                  'is_paid', 'create_at']
    
    def get_client_name(self, obj):
        if obj.client:
            return str(obj.client)
        return "Client de passage"
    
    def get_staff_name(self, obj):
        if obj.staff:
            return str(obj.staff)
        return "Vendeur inconnu"
