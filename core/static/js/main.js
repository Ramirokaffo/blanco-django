// Échapper une valeur avant insertion dans du HTML (texte ou attribut) : & < > " ' `
// null / undefined donnent une chaîne vide. Disponible globalement (main.js est chargé sur toutes les pages).
window.escapeHtml = function (value) {
    if (value === null || value === undefined) {
        return '';
    }
    const entities = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
        '`': '&#96;'
    };
    return String(value).replace(/[&<>"'`]/g, function (char) {
        return entities[char];
    });
};

// Restaurer l'état de la sidebar le plus tôt possible
try {
    const savedSidebarState = localStorage.getItem('sidebarCollapsed');
    const shouldCollapse = savedSidebarState === null
        ? window.matchMedia('(max-width: 768px)').matches
        : savedSidebarState === 'true';

    if (shouldCollapse) {
        document.body.classList.add('sidebar-collapsed');
    }
} catch (error) {
    if (window.matchMedia('(max-width: 768px)').matches) {
        document.body.classList.add('sidebar-collapsed');
    }
}

// Fonctions JavaScript principales
document.addEventListener('DOMContentLoaded', function() {
    const body = document.body;
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');
    const sidebarStorageKey = 'sidebarCollapsed';
    const mobileQuery = window.matchMedia('(max-width: 768px)');

    function setSidebarCollapsed(collapsed) {
        body.classList.toggle('sidebar-collapsed', collapsed);

        if (sidebarToggle) {
            sidebarToggle.setAttribute('aria-expanded', String(!collapsed));
            sidebarToggle.setAttribute(
                'aria-label',
                collapsed ? gettext('Ouvrir la navigation latérale') : gettext('Fermer la navigation latérale')
            );
        }

        if (sidebarBackdrop) {
            sidebarBackdrop.setAttribute('aria-hidden', collapsed ? 'true' : 'false');
        }

        try {
            localStorage.setItem(sidebarStorageKey, collapsed ? 'true' : 'false');
        } catch (error) {
            console.warn('Impossible de sauvegarder l\'état de la sidebar :', error);
        }
    }

    setSidebarCollapsed(body.classList.contains('sidebar-collapsed'));

    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function () {
            setSidebarCollapsed(!body.classList.contains('sidebar-collapsed'));
        });
    }

    if (sidebarBackdrop) {
        sidebarBackdrop.addEventListener('click', function () {
            setSidebarCollapsed(true);
        });
    }

    document.querySelectorAll('.navigation .nav-link').forEach(function (link) {
        link.addEventListener('click', function () {
            if (mobileQuery.matches) {
                setSidebarCollapsed(true);
            }
        });
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && mobileQuery.matches && !body.classList.contains('sidebar-collapsed')) {
            setSidebarCollapsed(true);
        }
    });

    
    // ── Recherche de fonctionnalités (command palette) ──────────
    const globalSearchInput = document.getElementById('globalSearchInput');
    const searchResultsDropdown = document.getElementById('searchResultsDropdown');
    let selectedIndex = -1;

    // Récupérer les pages disponibles depuis la navigation visible
    function buildFeatureRegistry() {
        const features = [];
        document.querySelectorAll('.nav-link').forEach(function(link) {
            const label = link.querySelector('span');
            if (label) {
                features.push({ name: label.textContent.trim(), url: link.getAttribute('href'), icon: '📄' });
            }
        });
        // Sous-pages qui n'apparaissent pas dans la nav principale
        const subPages = [
            { name: gettext('Historique des ventes'), url: '/sales/history/', keywords: gettext('vente historique liste'), icon: '🧾' },
            { name: gettext('Ajouter un approvisionnement'), url: '/supplies/add/', keywords: gettext('approvisionner ajouter créer stock'), icon: '➕' },
            { name: gettext('Ajouter un inventaire'), url: '/inventory/add/', keywords: gettext('inventaire ajouter créer'), icon: '➕' },
            { name: gettext('Historique des inventaires'), url: '/inventory/history/', keywords: gettext('inventaire historique liste'), icon: '📋' },
            { name: gettext('Clôture inventaire'), url: '/inventory/close/', keywords: gettext('inventaire clôturer fermer'), icon: '🔒' },
            { name: gettext('Ajouter un client'), url: '/contacts/clients/add/', keywords: gettext('client ajouter créer contact'), icon: '➕' },
            { name: gettext('Ajouter un fournisseur'), url: '/suppliers/add/', keywords: gettext('fournisseur ajouter créer'), icon: '➕' },
            { name: gettext('Ajouter une dépense'), url: '/expenses/add/', keywords: gettext('dépense ajouter créer'), icon: '➕' },
            { name: gettext('Résumé journalier'), url: '/daily/summary/', keywords: gettext('journée résumé quotidien bilan'), icon: '📊' },
            { name: gettext('Clôture journalière'), url: '/daily/close/', keywords: gettext('journée clôturer fermer quotidien'), icon: '🔒' },
            { name: gettext('Migration de données'), url: '/settings/migration/', keywords: gettext('migration données importer'), icon: '🔄' },
            { name: gettext('Journal comptable'), url: '/accounting/journal/', keywords: gettext('comptabilité journal écritures'), icon: '📒' },
            { name: gettext('Grand livre'), url: '/accounting/ledger/', keywords: gettext('comptabilité grand livre comptes'), icon: '📒' },
            { name: gettext('Balance des comptes'), url: '/accounting/balance/', keywords: gettext('comptabilité balance comptes'), icon: '📒' },
            { name: gettext('Plan comptable'), url: '/accounting/chart/', keywords: gettext('comptabilité plan comptes'), icon: '📒' },
            { name: gettext('Ventes à crédit'), url: '/accounting/credit-sales/', keywords: gettext('crédit vente impayé'), icon: '💳' },
            { name: gettext('Paiements fournisseurs'), url: '/accounting/supplier-payments/', keywords: gettext('paiement fournisseur'), icon: '💰' },
            { name: gettext('Factures'), url: '/accounting/invoices/', keywords: gettext('facture facturation'), icon: '🧾' },
            { name: gettext('Compte de résultat'), url: '/accounting/income-statement/', keywords: gettext('résultat bénéfice perte'), icon: '📈' },
            { name: gettext('Bilan comptable'), url: '/accounting/balance-sheet/', keywords: gettext('bilan actif passif'), icon: '📊' },
            { name: gettext('Balance âgée'), url: '/accounting/aged-balance/', keywords: gettext('balance âgée créance'), icon: '📊' },
            { name: gettext('Marges produits'), url: '/accounting/product-margins/', keywords: gettext('marge produit rentabilité'), icon: '📊' },
            { name: gettext('Déclaration TVA'), url: '/accounting/vat-declaration/', keywords: gettext('tva taxe déclaration'), icon: '📄' },
            { name: gettext('Rapprochement bancaire'), url: '/accounting/bank-reconciliation/', keywords: gettext('banque rapprochement'), icon: '🏦' },
            { name: gettext('Clôture d\'exercice'), url: '/accounting/exercise-closing/', keywords: gettext('exercice clôture fermer'), icon: '🔒' },
        ];
        subPages.forEach(function(sp) { sp.keywords = sp.keywords || ''; features.push(sp); });
        // Ajouter des keywords aux pages principales
        const kwMap = {
            [gettext('Tableau de bord')]: gettext('dashboard accueil résumé statistiques'),
            [gettext('Ventes')]: gettext('vendre caisse encaisser ticket'),
            [gettext('Produits')]: gettext('article produit catalogue stock'),
            [gettext('Fournisseurs')]: gettext('fournisseur partenaire'),
            [gettext('Approvisionnement')]: gettext('approvisionner stock entrée'),
            [gettext('Dépenses')]: gettext('dépense charge sortie argent'),
            [gettext('Utilisateurs')]: gettext('utilisateur contact client personnel'),
            [gettext('Inventaire')]: gettext('inventaire stock comptage'),
            [gettext('Comptabilité')]: gettext('comptable écriture journal'),
            [gettext('Trésorerie')]: gettext('trésorerie caisse banque argent'),
            [gettext('Rapports')]: gettext('rapport statistique export'),
            [gettext('Paramètres')]: gettext('paramètre réglage configuration'),
        };
        features.forEach(function(f) {
            if (!f.keywords && kwMap[f.name]) { f.keywords = kwMap[f.name]; }
            if (!f.keywords) f.keywords = '';
        });
        return features;
    }

    function filterFeatures(query) {
        const features = buildFeatureRegistry();
        const q = query.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        return features.filter(function(f) {
            const haystack = (f.name + ' ' + f.keywords).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
            return q.split(/\s+/).every(function(word) { return haystack.indexOf(word) !== -1; });
        });
    }

    function renderResults(results) {
        if (!searchResultsDropdown) return;
        if (results.length === 0) {
            searchResultsDropdown.innerHTML = '<div class="search-result-empty">' + gettext('Aucune fonctionnalité trouvée') + '</div>';
            searchResultsDropdown.classList.add('active');
            return;
        }
        searchResultsDropdown.innerHTML = results.map(function(r, i) {
            return '<a href="' + escapeHtml(r.url) + '" class="search-result-item' + (i === selectedIndex ? ' selected' : '') + '" data-index="' + i + '">'
                + '<span class="search-result-icon">' + escapeHtml(r.icon) + '</span>'
                + '<span class="search-result-name">' + escapeHtml(r.name) + '</span>'
                + '</a>';
        }).join('');
        searchResultsDropdown.classList.add('active');
    }

    function closeDropdown() {
        if (searchResultsDropdown) {
            searchResultsDropdown.classList.remove('active');
            searchResultsDropdown.innerHTML = '';
        }
        selectedIndex = -1;
    }

    if (globalSearchInput && searchResultsDropdown) {
        let currentResults = [];

        globalSearchInput.addEventListener('input', function() {
            const query = this.value.trim();
            selectedIndex = -1;
            if (query.length === 0) { closeDropdown(); return; }
            currentResults = filterFeatures(query);
            renderResults(currentResults);
        });

        globalSearchInput.addEventListener('keydown', function(e) {
            if (!searchResultsDropdown.classList.contains('active')) return;
            const items = searchResultsDropdown.querySelectorAll('.search-result-item');
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
                items.forEach(function(el, i) { el.classList.toggle('selected', i === selectedIndex); });
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                selectedIndex = Math.max(selectedIndex - 1, 0);
                items.forEach(function(el, i) { el.classList.toggle('selected', i === selectedIndex); });
            } else if (e.key === 'Enter') {
                e.preventDefault();
                if (selectedIndex >= 0 && items[selectedIndex]) {
                    window.location.href = items[selectedIndex].getAttribute('href');
                } else if (items.length > 0) {
                    window.location.href = items[0].getAttribute('href');
                }
            } else if (e.key === 'Escape') {
                closeDropdown();
                globalSearchInput.blur();
            }
        });

        // Fermer le dropdown au clic extérieur
        document.addEventListener('click', function(e) {
            if (!e.target.closest('.search-bar')) { closeDropdown(); }
        });

        // Focus avec Ctrl+K
        document.addEventListener('keydown', function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                globalSearchInput.focus();
                globalSearchInput.select();
            }
        });
    }
    
    // Gestion du menu utilisateur (dropdown)
    const userMenuBtn = document.getElementById('userMenuBtn');
    const userDropdown = document.getElementById('userDropdown');
    if (userMenuBtn && userDropdown) {
        userMenuBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            userDropdown.classList.toggle('open');
        });
        document.addEventListener('click', function () {
            userDropdown.classList.remove('open');
        });
    }

    // ── QR Code Modal ────────────────────────────────────────────
    const qrToggle = document.getElementById('qrToggle');
    const qrModal = document.getElementById('qrModal');
    const qrModalClose = document.getElementById('qrModalClose');

    if (qrToggle && qrModal) {
        qrToggle.addEventListener('click', function () {
            // 1. Afficher d'abord le modal avec le QR existant
            qrModal.classList.add('active');

            // 2. Lancer une requête pour vérifier si l'IP a changé
            fetch('/api/qr/refresh/')
                .then(response => response.json())
                .then(data => {
                    if (data.changed) {
                        // 3. Mettre à jour furtivement l'image et l'adresse
                        const qrImg = document.getElementById('qrCodeImg');
                        const qrAddr = document.getElementById('qrServerAddress');
                        if (qrImg && data.qr_base64) {
                            qrImg.src = 'data:image/png;base64,' + data.qr_base64;
                        }
                        if (qrAddr && data.server_address) {
                            qrAddr.textContent = data.server_address;
                        }
                    }
                })
                .catch(err => {
                    console.warn('Impossible de rafraîchir le QR code :', err);
                });
        });

        qrModalClose.addEventListener('click', function () {
            qrModal.classList.remove('active');
        });

        // Fermer en cliquant sur l'overlay
        qrModal.addEventListener('click', function (e) {
            if (e.target === qrModal) {
                qrModal.classList.remove('active');
            }
        });

        // Fermer avec Echap
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && qrModal.classList.contains('active')) {
                qrModal.classList.remove('active');
            }
        });
    }
    
    // Highlight du lien de navigation actif
    highlightActiveNavLink();
    
    // Animations au scroll
    initScrollAnimations();
});

// Fonction pour mettre en évidence le lien de navigation actif
function highlightActiveNavLink() {
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.nav-link');
    
    navLinks.forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });
}

// Fonction pour les animations au scroll
function initScrollAnimations() {
    const cards = document.querySelectorAll('.card');
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
            }
        });
    }, {
        threshold: 0.1
    });
    
    cards.forEach(card => {
        card.style.opacity = '0';
        card.style.transform = 'translateY(20px)';
        card.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
        observer.observe(card);
    });
}

// Fonction utilitaire pour formater les nombres
function formatNumber(num) {
    return new Intl.NumberFormat(document.documentElement.lang || 'fr').format(num);
}

// Fonction utilitaire pour formater les montants
function formatCurrency(amount) {
    return new Intl.NumberFormat(document.documentElement.lang || 'fr', {
        style: 'currency',
        currency: 'XOF'
    }).format(amount);
}

// Fonction utilitaire pour formater les dates
function formatDate(date) {
    return new Intl.DateTimeFormat(document.documentElement.lang || 'fr', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    }).format(new Date(date));
}

// Exporter les fonctions utilitaires
window.BlancoUtils = {
    formatNumber,
    formatCurrency,
    formatDate
};
