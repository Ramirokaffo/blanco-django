// Gestion du thème (Light/Dark Mode)
(function () {
    const VALID_THEMES = ['light', 'dark'];
    const DEFAULT_THEME = 'light';

    // Lit le thème sauvegardé en ne gardant que les valeurs connues.
    // Une valeur inattendue (ex. "system" écrite par une autre application
    // sur la même origine) ferait échouer les sélecteurs [data-theme="..."]
    // et rendrait toutes les variables CSS indéfinies.
    function readSavedTheme() {
        try {
            const saved = localStorage.getItem('theme');
            return VALID_THEMES.includes(saved) ? saved : DEFAULT_THEME;
        } catch (e) {
            return DEFAULT_THEME;
        }
    }

    function saveTheme(theme) {
        try {
            localStorage.setItem('theme', theme);
        } catch (e) {
            // Stockage indisponible (navigation privée, quota...) : on ignore
        }
    }

    function applyTheme(theme) {
        document.body.setAttribute('data-theme', theme);
    }

    document.addEventListener('DOMContentLoaded', function () {
        const themeToggle = document.getElementById('themeToggle');
        const body = document.body;

        const savedTheme = readSavedTheme();
        applyTheme(savedTheme);
        saveTheme(savedTheme); // normalise une éventuelle valeur invalide

        if (themeToggle) {
            themeToggle.addEventListener('click', function () {
                const currentTheme = body.getAttribute('data-theme');
                const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

                applyTheme(newTheme);
                saveTheme(newTheme);

                // Animation de transition
                body.style.transition = 'background-color 0.3s ease, color 0.3s ease';
            });
        }
    });
})();
