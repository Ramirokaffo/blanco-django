// Gestion de la page de vente
document.addEventListener('DOMContentLoaded', function() {
    // État du panier
    let cart = [];

    // Éléments DOM
    const newSaleBtn = document.getElementById('newSaleBtn');
    const closeSaleBtn = document.getElementById('closeSaleBtn');
    const newSaleSection = document.getElementById('newSaleSection');
    const productSearch = document.getElementById('productSearch');
    const searchResults = document.getElementById('searchResults');
    const cartItems = document.getElementById('cartItems');
    const clearCartBtn = document.getElementById('clearCartBtn');
    const completeSaleBtn = document.getElementById('completeSaleBtn');
    const saleTypeRadios = document.querySelectorAll('input[name="saleType"]');
    const creditDateGroup = document.getElementById('creditDateGroup');
    const toggleAdvancedBtn = document.getElementById('toggleAdvancedOptions');
    const advancedOptions = document.getElementById('advancedOptions');
    const saleNotification = document.getElementById('saleNotification');

    // Fonction pour afficher une notification
    function showNotification(message, type = 'info') {
        if (!saleNotification) return;

        // Supprimer les anciennes classes de type
        saleNotification.classList.remove('success', 'error', 'warning', 'info');

        // Ajouter la nouvelle classe de type
        saleNotification.classList.add(type);

        // Mettre à jour le message
        const messageElement = saleNotification.querySelector('.notification-message');
        if (messageElement) {
            messageElement.innerHTML = message;
        }

        // Afficher la notification
        saleNotification.style.display = 'block';

        // Auto-fermer après 5 secondes pour les succès et infos
        if (type === 'success' || type === 'info') {
            setTimeout(() => {
                closeSaleNotification();
            }, 5000);
        }
    }

    // Fonction pour fermer la notification
    window.closeSaleNotification = function() {
        if (saleNotification) {
            // Ajouter la classe de fermeture pour l'animation
            saleNotification.classList.add('closing');

            // Attendre la fin de l'animation avant de cacher
            setTimeout(() => {
                saleNotification.style.display = 'none';
                saleNotification.classList.remove('closing');
            }, 300);
        }
    };
    
    // Toggle nouvelle vente
    if (newSaleBtn) {
        newSaleBtn.addEventListener('click', function() {
            newSaleSection.style.display = 'block';
            newSaleSection.scrollIntoView({ behavior: 'smooth' });
            // Focus sur le champ de recherche
            setTimeout(() => {
                if (productSearch) productSearch.focus();
            }, 300);
        });
    }

    if (closeSaleBtn) {
        closeSaleBtn.addEventListener('click', function() {
            newSaleSection.style.display = 'none';
            clearCart();
        });
    }

    // Toggle options avancées (section pliable)
    if (toggleAdvancedBtn && advancedOptions) {
        toggleAdvancedBtn.addEventListener('click', function() {
            const isActive = advancedOptions.classList.contains('active');

            if (isActive) {
                advancedOptions.classList.remove('active');
                toggleAdvancedBtn.classList.remove('active');
            } else {
                advancedOptions.classList.add('active');
                toggleAdvancedBtn.classList.add('active');
            }
        });
    }
    
    // Gestion du type de vente (comptant/crédit)
    const paymentMethodSection = document.getElementById('paymentMethodSection');
    saleTypeRadios.forEach(radio => {
        radio.addEventListener('change', function() {
            if (this.value === 'credit') {
                creditDateGroup.style.display = 'block';
                if (paymentMethodSection) paymentMethodSection.style.display = 'none';
            } else {
                creditDateGroup.style.display = 'none';
                if (paymentMethodSection) paymentMethodSection.style.display = 'block';
            }
        });
    });
    
    // Recherche de produits
    let searchTimeout;
    if (productSearch) {
        productSearch.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            const query = this.value.trim();
            
            if (query.length < 2) {
                searchResults.classList.remove('active');
                searchResults.innerHTML = '';
                return;
            }
            
            searchTimeout = setTimeout(() => {
                searchProducts(query);
            }, 300);
        });
        
        // Fermer les résultats si on clique ailleurs
        document.addEventListener('click', function(e) {
            if (!productSearch.contains(e.target) && !searchResults.contains(e.target)) {
                searchResults.classList.remove('active');
            }
        });
    }
    
    // Fonction de recherche de produits
    function searchProducts(query) {
        searchResults.innerHTML = '<div class="search-result-item" style="padding: 20px; text-align: center; color: var(--text-secondary);">Recherche en cours...</div>';
        searchResults.classList.add('active');

        // Appel API réel
        fetch(`/api/products/search/?q=${encodeURIComponent(query)}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Erreur de recherche');
                }
                return response.json();
            })
            .then(data => {
                displaySearchResults(data);
            })
            .catch(error => {
                console.error('Erreur:', error);
                searchResults.innerHTML = '<div class="search-result-item" style="padding: 20px; text-align: center; color: var(--danger-color);">Erreur lors de la recherche</div>';
            });
    }
    
    // Afficher les résultats de recherche
    function displaySearchResults(products) {
        if (products.length === 0) {
            searchResults.innerHTML = '<div class="search-result-item" style="padding: 20px; text-align: center; color: var(--text-secondary);">Aucun produit trouvé</div>';
            return;
        }
        
        searchResults.innerHTML = products.map(product => `
            <div class="search-result-item" onclick="addToCart(${product.id}, '${product.name}', ${product.actual_price}, ${product.stock}, ${product.is_price_reducible})">
                <div class="product-name">${product.name}</div>
                <div class="product-info">
                    <span>Code: ${product.code}</span>
                    <span>Stock: ${product.stock}</span>
                    <span class="product-price">${formatCurrency(product.actual_price)}</span>
                </div>
            </div>
        `).join('');
    }
    
    // Ajouter au panier
    window.addToCart = function(productId, productName, price, stock, isPriceReducible) {
        // Vérifier si le produit est déjà dans le panier
        const existingItem = cart.find(item => item.id === productId);

        if (existingItem) {
            if (existingItem.quantity < stock) {
                existingItem.quantity++;
                updateCart();
                showNotification(`Quantité de "${productName}" mise à jour`, 'success');
            } else {
                showNotification(`Stock insuffisant pour "${productName}". Stock disponible: ${stock}`, 'warning');
            }
        } else {
            cart.push({
                id: productId,
                name: productName,
                price: price,
                quantity: 1,
                stock: stock,
                isPriceReducible: isPriceReducible
            });
            updateCart();
            showNotification(`"${productName}" ajouté au panier`, 'success');
        }

        // Réinitialiser la recherche
        productSearch.value = '';
        searchResults.classList.remove('active');
        searchResults.innerHTML = '';
    };
    
    // Mettre à jour l'affichage du panier
    function updateCart() {
        if (cart.length === 0) {
            cartItems.innerHTML = '<tr class="empty-cart"><td colspan="5" class="text-center">Le panier est vide</td></tr>';
            completeSaleBtn.disabled = true;
        } else {
            cartItems.innerHTML = cart.map((item, index) => `
                <tr class="cart-item-enter">
                    <td>${item.name}</td>
                    <td>
                        <input type="number"
                               min="0"
                               step="0.01"
                               value="${item.price}"
                               onchange="updatePrice(${index}, this.value)"
                               class="cart-price-input"
                               ${item.isPriceReducible ? '' : 'readonly'}>
                    </td>
                    <td>
                        <div class="quantity-control">
                            <button class="quantity-btn" onclick="decrementQuantity(${index})" title="Diminuer">
                                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                                    <path d="M2 6h8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                                </svg>
                            </button>
                            <input type="number"
                                   min="1"
                                   max="${item.stock}"
                                   value="${item.quantity}"
                                   onchange="updateQuantity(${index}, this.value)"
                                   class="cart-quantity-input">
                            <button class="quantity-btn" onclick="incrementQuantity(${index})" title="Augmenter">
                                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                                    <path d="M6 2v8M2 6h8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                                </svg>
                            </button>
                        </div>
                    </td>
                    <td class="font-weight-bold">${formatCurrency(calculateSubtotal(item))}</td>
                    <td>
                        <div class="cart-item-actions">
                            <button class="btn-icon" onclick="viewProductDetails(${item.id})" title="Voir détails">
                                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                                    <path d="M1 8s3-5 7-5 7 5 7 5-3 5-7 5-7-5-7-5z" stroke="currentColor" stroke-width="1.5"/>
                                    <circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.5"/>
                                </svg>
                            </button>
                            <button class="btn-icon btn-icon-danger" onclick="removeFromCart(${index})" title="Retirer">
                                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                                    <path d="M12 4L4 12M4 4l8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                                </svg>
                            </button>
                        </div>
                    </td>
                </tr>
            `).join('');
            completeSaleBtn.disabled = false;
        }

        updateTotals();
    }
    
    // Calculer le sous-total d'un article
    function calculateSubtotal(item) {
        return item.price * item.quantity;
    }

    // Mettre à jour le prix unitaire
    window.updatePrice = function(index, value) {
        const price = parseFloat(value);
        if (price >= 0) {
            cart[index].price = price;
            updateCart();
        } else {
            showNotification('Prix invalide. Le prix doit être supérieur ou égal à 0.', 'error');
            updateCart();
        }
    };

    // Mettre à jour la quantité
    window.updateQuantity = function(index, value) {
        const quantity = parseInt(value);
        if (quantity > 0 && quantity <= cart[index].stock) {
            cart[index].quantity = quantity;
            updateCart();
        } else {
            showNotification(`Quantité invalide. Stock disponible: ${cart[index].stock}`, 'error');
            updateCart();
        }
    };

    // Incrémenter la quantité
    window.incrementQuantity = function(index) {
        if (cart[index].quantity < cart[index].stock) {
            cart[index].quantity++;
            updateCart();
        } else {
            showNotification(`Stock maximum atteint pour "${cart[index].name}". Stock disponible: ${cart[index].stock}`, 'warning');
        }
    };

    // Décrémenter la quantité
    window.decrementQuantity = function(index) {
        if (cart[index].quantity > 1) {
            cart[index].quantity--;
            updateCart();
        } else {
            showNotification('La quantité minimale est 1. Utilisez le bouton de suppression pour retirer l\'article.', 'warning');
        }
    };
    
    // Retirer du panier
    window.removeFromCart = function(index) {
        cart.splice(index, 1);
        updateCart();
    };

    // Afficher les détails d'un produit dans un modal
    window.viewProductDetails = function(productId) {
        const modal = document.getElementById('productDetailsModal');
        const modalContent = document.getElementById('productDetailsContent');

        // Afficher le modal avec le spinner de chargement
        modal.style.display = 'flex';
        modalContent.innerHTML = `
            <div class="loading-spinner">
                <div class="spinner"></div>
                <p>Chargement des détails...</p>
            </div>
        `;

        // Récupérer les détails du produit
        fetch(`/api/products/${productId}/`)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Produit introuvable');
                }
                return response.json();
            })
            .then(product => {
                // Construire le HTML des détails du produit
                let imagesHtml = '';
                if (product.images && product.images.length > 0) {
                    imagesHtml = `
                        <div class="product-images">
                            ${product.images.map(img => `
                                <img src="${img.url}" alt="${product.name}" class="product-image ${img.is_main ? 'main-image' : ''}">
                            `).join('')}
                        </div>
                    `;
                } else {
                    imagesHtml = '<div class="no-image">Aucune image disponible</div>';
                }

                modalContent.innerHTML = `
                    <div class="product-details-grid">
                        <div class="product-images-section">
                            ${imagesHtml}
                        </div>
                        <div class="product-info-section">
                            <h2>${product.name}</h2>
                            <div class="product-detail-row">
                                <span class="detail-label">Code:</span>
                                <span class="detail-value">${product.code}</span>
                            </div>
                            ${product.brand ? `
                                <div class="product-detail-row">
                                    <span class="detail-label">Marque:</span>
                                    <span class="detail-value">${product.brand}</span>
                                </div>
                            ` : ''}
                            ${product.color ? `
                                <div class="product-detail-row">
                                    <span class="detail-label">Couleur:</span>
                                    <span class="detail-value">${product.color}</span>
                                </div>
                            ` : ''}
                            <div class="product-detail-row">
                                <span class="detail-label">Stock disponible:</span>
                                <span class="detail-value ${product.stock <= (product.stock_limit || 5) ? 'text-danger' : 'text-success'}">${product.stock}</span>
                            </div>
                            ${product.actual_price ? `
                                <div class="product-detail-row">
                                    <span class="detail-label">Prix actuel:</span>
                                    <span class="detail-value font-weight-bold">${formatCurrency(product.actual_price)}</span>
                                </div>
                            ` : ''}
                            ${product.max_salable_price ? `
                                <div class="product-detail-row">
                                    <span class="detail-label">Prix maximum:</span>
                                    <span class="detail-value">${formatCurrency(product.max_salable_price)}</span>
                                </div>
                            ` : ''}
                            <div class="product-detail-row">
                                <span class="detail-label">Prix modifiable:</span>
                                <span class="detail-value">${product.is_price_reducible ? '✓ Oui' : '✗ Non'}</span>
                            </div>
                            ${product.category ? `
                                <div class="product-detail-row">
                                    <span class="detail-label">Catégorie:</span>
                                    <span class="detail-value">${product.category.name}</span>
                                </div>
                            ` : ''}
                            ${product.gamme ? `
                                <div class="product-detail-row">
                                    <span class="detail-label">Gamme:</span>
                                    <span class="detail-value">${product.gamme.name}</span>
                                </div>
                            ` : ''}
                            ${product.rayon ? `
                                <div class="product-detail-row">
                                    <span class="detail-label">Rayon:</span>
                                    <span class="detail-value">${product.rayon.name}</span>
                                </div>
                            ` : ''}
                            ${product.grammage && product.grammage_type ? `
                                <div class="product-detail-row">
                                    <span class="detail-label">Grammage:</span>
                                    <span class="detail-value">${product.grammage} ${product.grammage_type.name}</span>
                                </div>
                            ` : ''}
                            ${product.description ? `
                                <div class="product-detail-row full-width">
                                    <span class="detail-label">Description:</span>
                                    <p class="detail-value">${product.description}</p>
                                </div>
                            ` : ''}
                        </div>
                    </div>
                `;
            })
            .catch(error => {
                console.error('Erreur:', error);
                modalContent.innerHTML = `
                    <div class="error-message">
                        <p>Erreur lors du chargement des détails du produit.</p>
                        <button class="btn btn-primary" onclick="closeProductModal()">Fermer</button>
                    </div>
                `;
            });
    };

    // Fermer le modal de détails du produit
    window.closeProductModal = function() {
        const modal = document.getElementById('productDetailsModal');
        modal.style.display = 'none';
    };
    
    // Vider le panier
    if (clearCartBtn) {
        clearCartBtn.addEventListener('click', function() {
            if (confirm('Voulez-vous vraiment vider le panier ?')) {
                clearCart();
            }
        });
    }
    
    function clearCart() {
        cart = [];
        updateCart();
    }
    
    // Mettre à jour les totaux
    function updateTotals() {
        const subtotal = cart.reduce((sum, item) => sum + (item.price * item.quantity), 0);
        const grandTotal = subtotal;

        // document.getElementById('subtotal').textContent = formatCurrency(subtotal);
        // document.getElementById('totalDiscount').textContent = formatCurrency(0);
        document.getElementById('grandTotal').textContent = formatCurrency(grandTotal);
    }
    
    // Valider la vente
    if (completeSaleBtn) {
        completeSaleBtn.addEventListener('click', function() {
            // Fermer toute notification précédente
            closeSaleNotification();

            if (cart.length === 0) {
                showNotification('Le panier est vide. Veuillez ajouter des produits avant de valider la vente.', 'warning');
                return;
            }

            const clientId = document.getElementById('clientSelect').value;
            const saleType = document.querySelector('input[name="saleType"]:checked').value;
            const dueDate = document.getElementById('dueDate').value;

            // Validation pour vente à crédit
            if (saleType === 'credit' && !dueDate) {
                showNotification('Veuillez sélectionner une date d\'échéance pour la vente à crédit.', 'error');
                return;
            }

            const paymentMethod = document.getElementById('paymentMethodSelect')?.value || 'CASH';

            const saleData = {
                client_id: clientId || null,
                is_credit: saleType === 'credit',
                due_date: dueDate || null,
                payment_method: saleType === 'credit' ? 'CASH' : paymentMethod,
                items: cart.map(item => ({
                    product_id: item.id,
                    quantity: item.quantity,
                    unit_price: item.price
                }))
            };

            const totalAmount = parseFloat(document.getElementById('grandTotal').textContent.replace(/[^\d]/g, ''));

            // Afficher un message de confirmation
            showNotification(`Validation de la vente en cours... Montant total: ${formatCurrency(totalAmount)}`, 'info');

            // Désactiver le bouton et afficher un loader
            completeSaleBtn.disabled = true;
            completeSaleBtn.classList.add('loading');

            fetch('/api/sales/create/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify(saleData)
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => {
                        throw err;
                    });
                }
                return response.json();
            })
            .then(data => {
                showNotification('✓ Vente enregistrée avec succès!', 'success');

                // Attendre 2 secondes avant de recharger pour que l'utilisateur voie le message
                setTimeout(() => {
                    clearCart();
                    newSaleSection.style.display = 'none';
                    location.reload();
                }, 2000);
            })
            .catch(error => {
                console.error('Erreur:', error);
                let errorMessage = '<strong>Erreur lors de l\'enregistrement de la vente</strong><br><br>';

                // Afficher les erreurs de validation de manière structurée
                if (error.items && Array.isArray(error.items)) {
                    errorMessage += '<strong>Erreurs sur les articles:</strong><ul style="margin: 8px 0; padding-left: 20px;">';
                    error.items.forEach((itemError, index) => {
                        if (itemError) {
                            Object.keys(itemError).forEach(key => {
                                errorMessage += `<li>Article ${index + 1} - ${key}: ${itemError[key]}</li>`;
                            });
                        }
                    });
                    errorMessage += '</ul>';
                } else if (typeof error === 'object') {
                    // Afficher toutes les erreurs de l'objet
                    Object.keys(error).forEach(key => {
                        if (key !== 'items') {
                            const value = error[key];
                            if (Array.isArray(value)) {
                                errorMessage += `<strong>${key}:</strong> ${value.join(', ')}<br>`;
                            } else if (typeof value === 'string') {
                                errorMessage += `<strong>${key}:</strong> ${value}<br>`;
                            } else {
                                errorMessage += `<strong>${key}:</strong> ${JSON.stringify(value)}<br>`;
                            }
                        }
                    });
                } else if (typeof error === 'string') {
                    errorMessage += error;
                } else {
                    errorMessage += 'Une erreur inattendue s\'est produite.';
                }

                showNotification(errorMessage, 'error');
            })
            .finally(() => {
                // Réactiver le bouton
                completeSaleBtn.disabled = false;
                completeSaleBtn.classList.remove('loading');
            });
        });
    }
    
    // Rechercher dans les ventes (côté backend)
    const searchSales = document.getElementById('searchSales');
    const searchSalesBtn = document.getElementById('searchSalesBtn');
    const salesTableBody = document.getElementById('salesTableBody');
    let salesSearchTimeout;

    if (searchSales && salesTableBody) {
        // Recherche automatique avec debounce
        searchSales.addEventListener('input', function() {
            const query = this.value.trim();

            // Débounce: attendre 500ms après la dernière frappe
            clearTimeout(salesSearchTimeout);
            salesSearchTimeout = setTimeout(() => {
                searchSalesBackend(query);
            }, 500);
        });

        // Recherche sur ENTER
        searchSales.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                clearTimeout(salesSearchTimeout);
                searchSalesBackend(this.value.trim());
            }
        });
    }

    // Bouton de recherche
    if (searchSalesBtn) {
        searchSalesBtn.addEventListener('click', function() {
            if (searchSales) {
                clearTimeout(salesSearchTimeout);
                searchSalesBackend(searchSales.value.trim());
            }
        });
    }

    // Fonction pour rechercher les ventes côté backend
    function searchSalesBackend(query) {
        // Afficher un indicateur de chargement
        salesTableBody.innerHTML = '<tr><td colspan="8" class="text-center">Recherche en cours...</td></tr>';

        // Construire l'URL avec le paramètre de recherche
        const url = query ? `/api/sales/search/?q=${encodeURIComponent(query)}` : '/api/sales/search/';

        fetch(url)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Erreur lors de la recherche');
                }
                return response.json();
            })
            .then(sales => {
                if (sales.length === 0) {
                    salesTableBody.innerHTML = '<tr><td colspan="8" class="text-center">Aucune vente trouvée</td></tr>';
                    return;
                }

                // Afficher les résultats
                salesTableBody.innerHTML = sales.map(sale => `
                    <tr>
                        <td>#${sale.id}</td>
                        <td>${formatDateTime(sale.create_at)}</td>
                        <td>${sale.client_name || '<span class="text-secondary">Client de passage</span>'}</td>
                        <td>${sale.staff_name || 'N/A'}</td>
                        <td class="font-weight-bold">${formatCurrency(sale.total)}</td>
                        <td>
                            ${sale.is_credit
                                ? '<span class="badge badge-warning">Crédit</span>'
                                : '<span class="badge badge-success">Comptant</span>'}
                        </td>
                        <td>
                            ${sale.is_paid
                                ? '<span class="badge badge-success">Payé</span>'
                                : '<span class="badge badge-danger">Non payé</span>'}
                        </td>
                        <td>
                            <div class="action-buttons">
                                <button class="btn-icon" onclick="viewSale(${sale.id})" title="Voir détails">
                                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                                        <path d="M1 8s3-5 7-5 7 5 7 5-3 5-7 5-7-5-7-5z" stroke="currentColor" stroke-width="1.5"/>
                                        <circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.5"/>
                                    </svg>
                                </button>
                                <button class="btn-icon" onclick="printSale(${sale.id})" title="Imprimer">
                                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                                        <path d="M4 5V2h8v3M4 11H2V7h12v4h-2" stroke="currentColor" stroke-width="1.5"/>
                                        <rect x="4" y="9" width="8" height="5" stroke="currentColor" stroke-width="1.5"/>
                                    </svg>
                                </button>
                            </div>
                        </td>
                    </tr>
                `).join('');
            })
            .catch(error => {
                console.error('Erreur:', error);
                salesTableBody.innerHTML = '<tr><td colspan="8" class="text-center text-danger">Erreur lors de la recherche des ventes</td></tr>';
            });
    }

    // Fonction pour formater la date et l'heure
    function formatDateTime(dateString) {
        if (!dateString) return 'N/A';
        const date = new Date(dateString);
        const day = String(date.getDate()).padStart(2, '0');
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const year = date.getFullYear();
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        return `${day}/${month}/${year} ${hours}:${minutes}`;
    }
    
    // Fonction pour obtenir le cookie CSRF
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
});

// Voir les détails d'une vente
function viewSale(saleId) {
    const modal = document.getElementById('saleDetailsModal');
    const modalContent = document.getElementById('saleDetailsContent');

    modalContent.innerHTML = '<p style="text-align: center; padding: 40px;">Chargement des détails...</p>';
    modal.classList.add('active');

    // Charger les détails via API
    fetch(`/api/sales/${saleId}/`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Vente introuvable');
            }
            return response.json();
        })
        .then(data => {
            const itemsHtml = data.items.map(item => `
                <tr>
                    <td>${item.product_name}</td>
                    <td>${item.product_code}</td>
                    <td>${item.quantity}</td>
                    <td>${formatCurrency(item.unit_price)}</td>
                    <td class="font-weight-bold">${formatCurrency(item.subtotal)}</td>
                </tr>
            `).join('');

            modalContent.innerHTML = `
                <div style="padding: 20px;">
                    <div style="margin-bottom: 20px;">
                        <h4 style="margin-bottom: 15px;">Vente #${data.id}</h4>
                        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; margin-bottom: 20px;">
                            <div>
                                <strong>Client:</strong> ${data.client_name}
                            </div>
                            <div>
                                <strong>Vendeur:</strong> ${data.staff_name}
                            </div>
                            <div>
                                <strong>Date:</strong> ${new Date(data.create_at).toLocaleString('fr-FR')}
                            </div>
                            <div>
                                <strong>Type:</strong>
                                <span class="badge ${data.is_credit ? 'badge-warning' : 'badge-success'}">
                                    ${data.is_credit ? 'Crédit' : 'Comptant'}
                                </span>
                            </div>
                            ${data.is_credit && data.credit_info ? `
                                <div>
                                    <strong>Date d'échéance:</strong> ${new Date(data.credit_info.due_date).toLocaleDateString('fr-FR')}
                                </div>
                            ` : ''}
                            <div>
                                <strong>Statut:</strong>
                                <span class="badge ${data.is_paid ? 'badge-success' : 'badge-danger'}">
                                    ${data.is_paid ? 'Payé' : 'Non payé'}
                                </span>
                            </div>
                        </div>
                    </div>

                    <h5 style="margin-bottom: 15px;">Articles</h5>
                    <div style="overflow-x: auto;">
                        <table class="table">
                            <thead>
                                <tr>
                                    <th>Produit</th>
                                    <th>Code</th>
                                    <th>Quantité</th>
                                    <th>Prix unitaire</th>
                                    <th>Sous-total</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${itemsHtml}
                            </tbody>
                        </table>
                    </div>

                    <div style="text-align: right; margin-top: 20px; padding-top: 20px; border-top: 2px solid var(--border-color);">
                        <h4 style="color: var(--primary-color);">Total: ${formatCurrency(data.total)}</h4>
                    </div>
                </div>
            `;
        })
        .catch(error => {
            console.error('Erreur:', error);
            modalContent.innerHTML = `
                <p style="text-align: center; padding: 40px; color: var(--danger-color);">
                    Erreur lors du chargement des détails
                </p>
            `;
        });
}

// Fonction utilitaire pour formater la monnaie (déplacée ici pour être accessible globalement)
function formatCurrency(amount) {
    return new Intl.NumberFormat('fr-FR', {
        style: 'decimal',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(amount) + ' FCFA';
}

// Fermer le modal
function closeModal() {
    const modal = document.getElementById('saleDetailsModal');
    modal.classList.remove('active');
}

// Imprimer une facture de vente
function printSale(saleId) {
    // Récupérer les détails de la vente via l'API
    fetch(`/api/sales/${saleId}/`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Vente introuvable');
            }
            return response.json();
        })
        .then(data => {
            openInvoicePrintWindow(data);
        })
        .catch(error => {
            console.error('Erreur lors du chargement de la facture:', error);
            alert('Impossible de charger les détails de la vente pour l\'impression.');
        });
}

// Ouvrir une fenêtre d'impression avec la facture formatée
function openInvoicePrintWindow(sale) {
    const printWindow = window.open('', '_blank', 'width=400,height=700');
    if (!printWindow) {
        alert('Le navigateur a bloqué l\'ouverture de la fenêtre. Veuillez autoriser les popups.');
        return;
    }

    // Récupérer les paramètres système
    const settings = window.SYSTEM_SETTINGS || {};
    const companyName = settings.companyName || 'BLANCO';
    const companyLogo = settings.companyLogo || '';
    const companyAddress = settings.companyAddress || '';
    const companyPhone = settings.companyPhone || '';
    const companyEmail = settings.companyEmail || '';
    const currencySymbol = settings.currencySymbol || 'FCFA';
    const receiptFooter = settings.receiptFooter || 'Merci pour votre achat !';

    const invoiceDate = sale.create_at
        ? new Date(sale.create_at).toLocaleDateString('fr-FR', {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        })
        : 'N/A';

    // Construire les lignes des articles pour ticket thermique
    const itemsLines = sale.items.map((item, index) => `
        <div class="item-line">
            <span class="item-name">${index + 1}. ${item.product_name}</span>
            <span class="item-detail">${item.quantity} x ${formatCurrencyPlain(item.unit_price)} = ${formatCurrencyPlain(item.subtotal)} ${currencySymbol}</span>
        </div>
    `).join('');

    // Infos de crédit si applicable
    let creditHtml = '';
    if (sale.is_credit && sale.credit_info) {
        const dueDate = sale.credit_info.due_date
            ? new Date(sale.credit_info.due_date).toLocaleDateString('fr-FR')
            : 'N/A';
        creditHtml = `
            <div class="separator">=</div>
            <div class="section-title">** CREDIT **</div>
            <div class="info-line"><span>Payé</span><span>${formatCurrencyPlain(sale.credit_info.amount_paid)} ${currencySymbol}</span></div>
            <div class="info-line"><span>Reste</span><span>${formatCurrencyPlain(sale.credit_info.amount_remaining)} ${currencySymbol}</span></div>
            <div class="info-line"><span>Échéance</span><span>${dueDate}</span></div>
        `;
    }

    const invoiceHtml = `
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Ticket #${sale.id} - ${companyName}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Courier New', 'Lucida Console', monospace;
            font-size: 12px;
            color: #000;
            width: 302px;
            max-width: 302px;
            margin: 0 auto;
            padding: 8px;
        }
        .receipt { width: 100%; }
        .center { text-align: center; }
        .bold { font-weight: bold; }
        .separator {
            text-align: center;
            letter-spacing: 2px;
            margin: 4px 0;
            overflow: hidden;
        }
        .separator::before {
            content: '------------------------------------------------';
        }
        .separator.double::before {
            content: '================================================';
        }
        .header {
            text-align: center;
            margin-bottom: 4px;
        }
        .header img {
            height: 40px;
            width: auto;
            object-fit: contain;
            margin-bottom: 4px;
        }
        .header .company-name {
            font-size: 16px;
            font-weight: bold;
            letter-spacing: 1px;
        }
        .header .company-info {
            font-size: 10px;
            color: #333;
        }
        .section-title {
            text-align: center;
            font-weight: bold;
            font-size: 13px;
            margin: 4px 0 2px 0;
            letter-spacing: 1px;
        }
        .info-line {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            line-height: 1.6;
        }
        .info-line span:first-child {
            color: #555;
        }
        .item-line {
            margin: 3px 0;
            padding: 2px 0;
            border-bottom: 1px dotted #ccc;
        }
        .item-name {
            display: block;
            font-size: 11px;
            font-weight: bold;
        }
        .item-detail {
            display: block;
            font-size: 11px;
            text-align: right;
            color: #333;
        }
        .total-line {
            display: flex;
            justify-content: space-between;
            font-size: 15px;
            font-weight: bold;
            margin: 6px 0;
            padding: 4px 0;
        }
        .footer {
            text-align: center;
            font-size: 10px;
            color: #555;
            margin-top: 6px;
        }
        .footer p { margin: 2px 0; }
        @media print {
            body { padding: 0; margin: 0; width: 100%; max-width: 100%; }
            .no-print { display: none !important; }
        }
        @media screen {
            body {
                padding: 20px;
                background: #f0f0f0;
            }
            .receipt {
                background: white;
                padding: 15px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.15);
                border-radius: 2px;
            }
        }
    </style>
</head>
<body>
<div class="receipt">

    <!-- EN-TÊTE -->
    <div class="header">
        ${companyLogo ? `<img src="${companyLogo}" alt="${companyName}">` : ''}
        <div class="company-name">${companyName}</div>
        ${companyAddress ? `<div class="company-info">${companyAddress}</div>` : ''}
        ${companyPhone ? `<div class="company-info">Tél: ${companyPhone}</div>` : ''}
        ${companyEmail ? `<div class="company-info">${companyEmail}</div>` : ''}
    </div>

    <div class="separator double"></div>

    <!-- FACTURE -->
    <div class="section-title">FACTURE N° ${sale.id}</div>
    <div class="info-line"><span>Date</span><span>${invoiceDate}</span></div>
    <div class="info-line"><span>Type</span><span>${sale.is_credit ? 'Crédit' : 'Comptant'}</span></div>
    <div class="info-line"><span>Statut</span><span>${sale.is_paid ? 'Payé' : 'Non payé'}</span></div>

    <div class="separator"></div>

    <!-- CLIENT & VENDEUR -->
    <div class="info-line"><span>Client</span><span class="bold">${sale.client_name || 'Passage'}</span></div>
    <div class="info-line"><span>Vendeur</span><span class="bold">${sale.staff_name || 'N/A'}</span></div>

    <div class="separator double"></div>

    <!-- ARTICLES -->
    <div class="section-title">ARTICLES</div>
    ${itemsLines}

    <div class="separator double"></div>

    <!-- TOTAL -->
    <div class="total-line">
        <span>TOTAL</span>
        <span>${formatCurrencyPlain(sale.total)} ${currencySymbol}</span>
    </div>

    ${creditHtml}

    <div class="separator"></div>

    <!-- PIED DE PAGE -->
    <div class="footer">
        <p class="bold">${receiptFooter}</p>
        <p>${new Date().toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}</p>
    </div>

</div>

    <div class="no-print" style="text-align:center; margin-top:15px;">
        <button onclick="window.print()" style="padding:8px 20px; font-size:13px; background:#333; color:white; border:none; border-radius:4px; cursor:pointer;">
            🖨️ Imprimer
        </button>
        <button onclick="window.close()" style="padding:8px 20px; font-size:13px; background:#999; color:white; border:none; border-radius:4px; cursor:pointer; margin-left:8px;">
            Fermer
        </button>
    </div>
</body>
</html>`;

    printWindow.document.write(invoiceHtml);
    printWindow.document.close();

    // Lancer l'impression automatiquement après le chargement
    printWindow.onload = function() {
        printWindow.print();
    };
}

// Formater un montant sans le suffixe FCFA (pour la facture)
function formatCurrencyPlain(amount) {
    return new Intl.NumberFormat('fr-FR', {
        style: 'decimal',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(amount);
}

// Fermer le modal en cliquant en dehors
document.addEventListener('click', function(e) {
    const modal = document.getElementById('saleDetailsModal');
    if (e.target === modal) {
        closeModal();
    }
});
