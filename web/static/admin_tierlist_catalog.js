document.querySelectorAll('[data-json-form]').forEach((form) => {
    const editor = form.querySelector('[data-json-editor]');
    const status = form.querySelector('[data-json-status]');

    const parse = () => {
        try {
            const value = JSON.parse(editor.value);
            status.classList.remove('is-error');
            status.textContent = 'Синтаксис JSON корректен. Семантика полей проверяется при сохранении.';
            return value;
        } catch (error) {
            status.classList.add('is-error');
            status.textContent = error.message;
            return null;
        }
    };

    form.querySelector('[data-json-check]')?.addEventListener('click', parse);
    form.querySelector('[data-json-format]')?.addEventListener('click', () => {
        const value = parse();
        if (value !== null) {
            editor.value = JSON.stringify(value, null, 2);
        }
    });
    form.addEventListener('submit', (event) => {
        try {
            JSON.parse(editor.value);
        } catch (error) {
            event.preventDefault();
            parse();
            editor.focus();
        }
    });
});
