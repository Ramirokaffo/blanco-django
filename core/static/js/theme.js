// Gestion du thème (Light/Dark Mode)
document.addEventListener('DOMContentLoaded', function() {
    const themeToggle = document.getElementById('themeToggle');
    const body = document.body;
    
    // Récupérer le thème sauvegardé ou utiliser 'light' par défaut
    const savedTheme = localStorage.getItem('theme') || 'light';
    body.setAttribute('data-theme', savedTheme);
    
    // Écouter le clic sur le bouton de changement de thème
    if (themeToggle) {
        themeToggle.addEventListener('click', function() {
            const currentTheme = body.getAttribute('data-theme');
            const newTheme = currentTheme === 'light' ? 'dark' : 'light';
            
            body.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            
            // Animation de transition
            body.style.transition = 'background-color 0.3s ease, color 0.3s ease';
        });
    }
});
