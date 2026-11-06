function showAdminToast(message, isError = false) {
    let container = document.querySelector('.admin-toasts');
    if (!container) {
        container = document.createElement('div');
        container.className = 'admin-toasts';
        container.setAttribute('aria-live', 'polite');
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `admin-toast ${isError ? 'is-error' : 'is-success'}`;
    toast.setAttribute('role', isError ? 'alert' : 'status');
    const text = document.createElement('span');
    text.textContent = message;
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'admin-toast-close';
    close.setAttribute('aria-label', 'Закрыть уведомление');
    close.textContent = '×';
    close.addEventListener('click', () => toast.remove());
    toast.append(text, close);
    container.appendChild(toast);
    window.setTimeout(() => toast.remove(), 6000);
}

function setAdminPanelCollapsed(panel, collapsed) {
    if (panel.matches('details')) {
        panel.open = !collapsed;
        return;
    }
    panel.classList.toggle('is-collapsed', collapsed);
    const button = panel.querySelector(':scope > .admin-panel-toggle');
    if (button) {
        button.textContent = collapsed ? '+' : '−';
        button.setAttribute('aria-expanded', String(!collapsed));
        button.setAttribute('aria-label', collapsed ? 'Развернуть блок' : 'Свернуть блок');
        button.title = collapsed ? 'Развернуть блок' : 'Свернуть блок';
    }
}

function configureAdminPanels(root = document) {
    root.querySelectorAll('.panel:not(.collapsible-panel)').forEach((panel) => {
        if (panel.querySelector(':scope > .admin-panel-toggle')) {
            return;
        }
        const content = document.createElement('div');
        content.className = 'admin-panel-content';
        while (panel.firstChild) {
            content.appendChild(panel.firstChild);
        }
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'admin-panel-toggle';
        panel.append(button, content);
        setAdminPanelCollapsed(panel, false);
    });
}

function configureAdminLocalSearch(search) {
    const dropdown = search.closest('[data-filter-dropdown]');
    const options = [...dropdown.querySelectorAll('[data-tag-option]')];
    const empty = dropdown.querySelector('[data-tag-empty]');
    search.addEventListener('input', () => {
        const query = search.value.trim().toLowerCase();
        let visible = 0;
        options.forEach((option) => {
            option.hidden = query && !option.textContent.toLowerCase().includes(query);
            if (!option.hidden) {
                visible += 1;
            }
        });
        empty.hidden = visible > 0;
    });
}

function configureAdminContent(main) {
    main.querySelectorAll('video').forEach(configureVideo);
    main.querySelectorAll('[data-filter-dropdown]').forEach(configureFilterDropdown);
    main.querySelectorAll('[data-local-search]').forEach(configureAdminLocalSearch);
    main.querySelectorAll('[data-date-range]').forEach(configureDateRangePicker);
    configureAdminPanels(main);
}

function captureAdminPanelStates(main) {
    return [...main.querySelectorAll('.panel')].map((panel) => (
        panel.matches('details') ? !panel.open : panel.classList.contains('is-collapsed')
    ));
}

function restoreAdminPanelStates(main, states) {
    main.querySelectorAll('.panel').forEach((panel, index) => {
        if (states[index] !== undefined) {
            setAdminPanelCollapsed(panel, states[index]);
        }
    });
}

function adminSuccessMessage(action) {
    if (action.includes('/delete')) {
        return 'Удаление выполнено';
    }
    if (/\/(edit|status|visibility|assign)(\/)?$/.test(action)) {
        return 'Изменения сохранены';
    }
    return 'Создание выполнено';
}

function updateAdminMediaVisibility(form) {
    const input = form.querySelector('input[name="is_public"]');
    const card = form.closest('.media-card');
    const isPublic = input.value === 'true';
    input.value = String(!isPublic);
    form.querySelector('button[type="submit"]').textContent = isPublic ? 'Скрыть' : 'Показать';
    card?.classList.toggle('media-hidden', !isPublic);
}

document.addEventListener('click', (event) => {
    const button = event.target.closest('.admin-panel-toggle');
    if (!button) {
        return;
    }
    const panel = button.closest('.panel');
    setAdminPanelCollapsed(panel, !panel.classList.contains('is-collapsed'));
});

document.addEventListener('submit', async (event) => {
    const form = event.target;
    if (!document.querySelector('.admin-toolbar') || !form.matches('form[method="post"]')) {
        return;
    }
    const action = new URL(form.action);
    if (action.origin !== window.location.origin || !action.pathname.startsWith('/admin/')
        || action.pathname === '/admin/logout') {
        return;
    }
    event.preventDefault();
    if (form.dataset.pending === 'true') {
        return;
    }
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
        return;
    }

    form.dataset.pending = 'true';
    form.setAttribute('aria-busy', 'true');
    const submitter = event.submitter;
    if (submitter) {
        submitter.disabled = true;
    }
    const scrollPosition = {x: window.scrollX, y: window.scrollY};
    try {
        let response = await fetch(action, {
            method: 'POST',
            body: new FormData(form),
            headers: {'X-Requested-With': 'XMLHttpRequest'},
            credentials: 'same-origin',
        });
        let html = await response.text();
        let parsed = new DOMParser().parseFromString(html, 'text/html');
        const error = parsed.querySelector('.form-error')?.textContent.trim();
        if (response.ok && /\/(edit|status)$/.test(action.pathname)) {
            response = await fetch(window.location.href, {
                headers: {'X-Requested-With': 'XMLHttpRequest'},
                credentials: 'same-origin',
            });
            html = await response.text();
            parsed = new DOMParser().parseFromString(html, 'text/html');
        }
        const nextMain = parsed.querySelector('main.page');

        if (response.redirected && !parsed.querySelector('.admin-toolbar')) {
            window.location.assign(response.url);
            return;
        }
        if (form.matches('form[action*="/admin/media/"]')) {
            if (response.ok) {
                updateAdminMediaVisibility(form);
            }
        } else if (nextMain && parsed.querySelector('.admin-toolbar')) {
            const currentMain = document.querySelector('main.page');
            const panelStates = captureAdminPanelStates(currentMain);
            currentMain.replaceChildren(...nextMain.childNodes);
            document.title = parsed.title;
            history.replaceState(null, '', response.url);
            configureAdminContent(currentMain);
            restoreAdminPanelStates(currentMain, panelStates);
            window.scrollTo(scrollPosition.x, scrollPosition.y);
        }
        showAdminToast(
            response.ok ? adminSuccessMessage(action.pathname) : error || `Не удалось выполнить действие (${response.status})`,
            !response.ok,
        );
    } catch (error) {
        showAdminToast('Не удалось связаться с сервером. Проверьте соединение и повторите действие.', true);
    } finally {
        form.dataset.pending = 'false';
        form.setAttribute('aria-busy', 'false');
        if (submitter?.isConnected) {
            submitter.disabled = false;
        }
    }
});

configureAdminPanels();
