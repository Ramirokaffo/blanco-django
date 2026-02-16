# API - Mise à jour de produit par code

## Endpoint

```
PATCH /api/products/by-code/<product_code>/update/
```

## Description

Cet endpoint permet de mettre à jour un produit existant en utilisant son code produit.

## Authentification

**Requise** : Oui  
**Type** : Token Authentication  
**Header** : `Authorization: Token <votre_token>`

## Paramètres d'URL

| Paramètre | Type | Description |
|-----------|------|-------------|
| `product_code` | string | Code unique du produit à modifier |

## Corps de la requête (JSON ou FormData)

Tous les champs sont **optionnels** (partial update). Seuls les champs fournis seront mis à jour.

| Champ | Type | Description |
|-------|------|-------------|
| `code` | string | Nouveau code du produit |
| `name` | string | Nom du produit |
| `description` | string | Description du produit |
| `brand` | string | Marque du produit |
| `color` | string | Couleur du produit |
| `stock` | integer | Quantité en stock |
| `stock_limit` | integer | Seuil d'alerte de stock |
| `max_salable_price` | decimal | Prix de vente maximum |
| `actual_price` | decimal | Prix actuel |
| `is_price_reducible` | boolean | Le prix est-il réductible ? |
| `grammage` | float | Grammage du produit |
| `exp_alert_period` | integer | Période d'alerte d'expiration (jours) |
| `category` | integer | ID de la catégorie |
| `gamme` | integer | ID de la gamme |
| `rayon` | integer | ID du rayon |
| `grammage_type` | integer | ID du type de grammage |
| `images` | file[] | Liste de nouvelles images à ajouter |

## Réponse

### Succès (200 OK)

```json
{
  "status": 1,
  "product": {
    "id": 123,
    "code": "PROD001",
    "name": "Produit mis à jour",
    "description": "Description mise à jour",
    "brand": "Marque",
    "color": "Rouge",
    "stock": 50,
    "stock_limit": 10,
    "max_salable_price": "1500.00",
    "actual_price": "1200.00",
    "is_price_reducible": true,
    "grammage": 500.0,
    "exp_alert_period": 30,
    "category": {
      "id": 1,
      "name": "Catégorie A",
      "description": "..."
    },
    "gamme": { ... },
    "rayon": { ... },
    "grammage_type": { ... },
    "images": [
      {
        "id": 1,
        "image_path": "image1.jpg",
        "image_url": "http://localhost:8000/api/images/product/image1.jpg",
        "is_primary": true
      }
    ],
    "create_at": "2024-01-15T10:30:00Z",
    "delete_at": null
  }
}
```

### Erreur - Produit non trouvé (404 NOT FOUND)

```json
{
  "status": 0,
  "error": "Produit non trouvé"
}
```

### Erreur - Validation (400 BAD REQUEST)

```json
{
  "status": 0,
  "errors": {
    "code": ["Ce code produit existe déjà."],
    "stock": ["Ce champ doit être un nombre entier."]
  }
}
```

### Erreur - Non authentifié (401 UNAUTHORIZED)

```json
{
  "detail": "Les informations d'authentification n'ont pas été fournies."
}
```

## Exemples d'utilisation

### cURL - Mise à jour simple (JSON)

```bash
curl -X PATCH \
  http://localhost:8000/api/products/by-code/PROD001/update/ \
  -H "Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Nouveau nom",
    "actual_price": "1500.00",
    "stock": 75
  }'
```

### cURL - Mise à jour avec images (FormData)

```bash
curl -X PATCH \
  http://localhost:8000/api/products/by-code/PROD001/update/ \
  -H "Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b" \
  -F "name=Nouveau nom" \
  -F "actual_price=1500.00" \
  -F "images=@/path/to/image1.jpg" \
  -F "images=@/path/to/image2.jpg"
```

### JavaScript/Fetch - JSON

```javascript
const token = "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b";
const productCode = "PROD001";

fetch(`http://localhost:8000/api/products/by-code/${productCode}/update/`, {
  method: 'PATCH',
  headers: {
    'Authorization': `Token ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    name: "Nouveau nom",
    actual_price: "1500.00",
    stock: 75
  })
})
.then(response => response.json())
.then(data => console.log(data));
```

