/**
 * Products page – filter interactions
 */
document.addEventListener('DOMContentLoaded', function () {

    const form = document.getElementById('filtersForm');
    if (!form) return;

    // Auto-submit quand on change un select
    form.querySelectorAll('select').forEach(function (select) {
        select.addEventListener('change', function () {
            form.submit();
        });
    });

    // Soumettre avec Enter dans le champ recherche (comportement par défaut du form, mais
    // on s'assure que la page se recharge correctement)
    const searchInput = form.querySelector('input[name="search"]');
    if (searchInput) {
        searchInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                form.submit();
            }
        });
    }
});

