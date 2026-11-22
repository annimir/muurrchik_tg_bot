(() => {
    const dialog = document.querySelector('#cycle-details-dialog');
    if (!dialog) return;
    const content = dialog.querySelector('[data-cycle-details-content]');
    dialog.querySelector('[data-cycle-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', (event) => {
        if (event.target === dialog) dialog.close();
    });
    document.addEventListener('click', async (event) => {
        const trigger = event.target.closest('[data-cycle-id]');
        if (!trigger) return;
        event.preventDefault();
        try {
            const response = await fetch(`/calendar/cycles/${trigger.dataset.cycleId}`, {
                headers: {'X-Requested-With': 'XMLHttpRequest'}, credentials: 'same-origin',
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            content.innerHTML = data.html;
            dialog.showModal();
        } catch (error) {
            content.innerHTML = '<p>Не удалось загрузить подробности цикла.</p>';
            dialog.showModal();
        }
    });
})();
