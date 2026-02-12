// Fonctions JavaScript principales
document.addEventListener('DOMContentLoaded', function() {
    
    // Gestion de la recherche
    const searchInput = document.querySelector('.search-input');
    const searchBtn = document.querySelector('.search-btn');
    
    if (searchBtn) {
        searchBtn.addEventListener('click', function() {
            performSearch();
        });
    }
    
    if (searchInput) {
        searchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                performSearch();
            }
        });
    }
    
    function performSearch() {
        const query = searchInput.value.trim();
        if (query) {
            console.log('Recherche:', query);
            // TODO: Implémenter la logique de recherche
        }
    }
    
    // Gestion du menu utilisateur
    const userBtn = document.querySelector('.user-btn');
    if (userBtn) {
        userBtn.addEventListener('click', function() {
            console.log('Menu utilisateur cliqué');
            // TODO: Afficher le menu déroulant utilisateur
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
    return new Intl.NumberFormat('fr-FR').format(num);
}

// Fonction utilitaire pour formater les montants
function formatCurrency(amount) {
    return new Intl.NumberFormat('fr-FR', {
        style: 'currency',
        currency: 'XOF'
    }).format(amount);
}

// Fonction utilitaire pour formater les dates
function formatDate(date) {
    return new Intl.DateTimeFormat('fr-FR', {
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
