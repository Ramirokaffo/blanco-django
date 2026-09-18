// Interactions de la page de connexion
document.addEventListener('DOMContentLoaded', function () {
    const form = document.querySelector('.login-form');
    const submitBtn = document.getElementById('loginSubmit');
    const toggleBtn = document.getElementById('togglePassword');
    const passwordInput = document.getElementById('id_password');

    // Afficher / masquer le mot de passe
    if (toggleBtn && passwordInput) {
        toggleBtn.addEventListener('click', function () {
            const show = passwordInput.type === 'password';
            passwordInput.type = show ? 'text' : 'password';
            toggleBtn.classList.toggle('is-visible', show);
            toggleBtn.setAttribute('aria-pressed', show ? 'true' : 'false');
            const label = show ? gettext('Masquer le mot de passe') : gettext('Afficher le mot de passe');
            toggleBtn.setAttribute('aria-label', label);
            toggleBtn.setAttribute('title', label);
            passwordInput.focus();
        });
    }

    // État de chargement du bouton pendant la soumission
    if (form && submitBtn) {
        form.addEventListener('submit', function (event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                form.reportValidity();
                return;
            }
            submitBtn.classList.add('is-loading');
            // Désactivé après l'envoi pour ne pas bloquer la soumission elle-même
            setTimeout(function () { submitBtn.disabled = true; }, 0);
        });

        // Retour arrière (bfcache) : on remet le bouton dans son état initial
        window.addEventListener('pageshow', function () {
            submitBtn.classList.remove('is-loading');
            submitBtn.disabled = false;
        });
    }
});
