function configureVideo(video) {
    video.muted = true;
    video.volume = 0.4;
}

document.querySelectorAll('video').forEach(configureVideo);

document.addEventListener('error', (event) => {
    if (event.target.matches('[data-avatar-image]')) {
        event.target.closest('.profile-initial')?.classList.add('avatar-missing');
    }
}, true);

const mediaDialog = document.querySelector('#media-dialog');
if (mediaDialog) {
    const content = mediaDialog.querySelector('.media-dialog-content');

    const closeDialog = () => {
        content.querySelectorAll('video').forEach((video) => video.pause());
        mediaDialog.close();
    };

    document.querySelectorAll('[data-media-open]').forEach((trigger) => {
        trigger.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            content.replaceChildren();
            const source = trigger.dataset.mediaOpen;
            let media;
            if (trigger.dataset.mediaKind === 'video') {
                media = document.createElement('video');
                media.controls = true;
                media.playsInline = true;
                configureVideo(media);
            } else {
                media = document.createElement('img');
                media.alt = 'Полноразмерное изображение';
            }
            media.src = source;
            content.appendChild(media);
            mediaDialog.showModal();
            document.body.classList.add('dialog-open');
        });
    });

    mediaDialog.querySelector('[data-media-close]').addEventListener('click', closeDialog);
    mediaDialog.addEventListener('click', (event) => {
        if (event.target === mediaDialog) {
            closeDialog();
        }
    });
    mediaDialog.addEventListener('close', () => {
        content.querySelectorAll('video').forEach((video) => video.pause());
        content.replaceChildren();
        document.body.classList.remove('dialog-open');
    });
}

const usersSentinel = document.querySelector('[data-users-sentinel]');
if (usersSentinel) {
    const grid = document.querySelector('[data-users-grid]');
    let loading = false;

    const loadMoreUsers = async () => {
        const nextUrl = usersSentinel.dataset.nextUrl;
        if (loading || !nextUrl) {
            return;
        }
        loading = true;
        usersSentinel.setAttribute('aria-busy', 'true');
        usersSentinel.textContent = 'Загружаем игроков…';
        try {
            const response = await fetch(nextUrl, {
                headers: {'X-Requested-With': 'XMLHttpRequest'},
                credentials: 'same-origin',
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            grid.insertAdjacentHTML('beforeend', payload.html);
            usersSentinel.dataset.nextUrl = payload.next_url || '';
            usersSentinel.textContent = payload.next_url ? 'Прокрутите ниже для загрузки' : 'Все игроки загружены';
            if (!payload.next_url) {
                usersSentinel.classList.add('is-complete');
            }
        } catch (error) {
            usersSentinel.textContent = 'Не удалось загрузить. Нажмите, чтобы повторить.';
        } finally {
            loading = false;
            usersSentinel.setAttribute('aria-busy', 'false');
        }
    };

    usersSentinel.addEventListener('click', loadMoreUsers);
    const observer = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
            loadMoreUsers();
        }
    }, {rootMargin: '300px'});
    observer.observe(usersSentinel);
}

const usersSearchForm = document.querySelector('[data-users-search]');
if (usersSearchForm) {
    const input = usersSearchForm.querySelector('input[name="q"]');
    const searchGrid = document.querySelector('[data-users-grid]');
    const resultCount = document.querySelector('[data-users-count]');
    const emptyState = document.querySelector('[data-users-empty]');
    let searchTimer;
    let searchController;

    const searchUsers = async () => {
        const query = input.value.trim();
        if (searchController) {
            searchController.abort();
        }
        searchController = new AbortController();
        try {
            const response = await fetch(`/users/fragment?${new URLSearchParams({q: query, page: 1})}`, {
                signal: searchController.signal,
                credentials: 'same-origin',
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            searchGrid.innerHTML = payload.html;
            resultCount.textContent = `Найдено: ${payload.total}`;
            emptyState.hidden = payload.total > 0;
            if (usersSentinel) {
                usersSentinel.dataset.nextUrl = payload.next_url || '';
                usersSentinel.textContent = payload.next_url ? 'Прокрутите ниже для загрузки' : 'Все игроки загружены';
                usersSentinel.classList.toggle('is-complete', !payload.next_url);
            }
            history.replaceState(null, '', `/users${query ? `?q=${encodeURIComponent(query)}` : ''}`);
        } catch (error) {
            if (error.name !== 'AbortError') {
                resultCount.textContent = 'Не удалось выполнить поиск';
            }
        }
    };

    input.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(searchUsers, 250);
    });
    usersSearchForm.addEventListener('submit', (event) => {
        event.preventDefault();
        clearTimeout(searchTimer);
        searchUsers();
    });
}

const dateRangePicker = document.querySelector('[data-date-range]');
if (dateRangePicker) {
    const fromInput = dateRangePicker.querySelector('input[name="date_from"]');
    const toInput = dateRangePicker.querySelector('input[name="date_to"]');
    const toggle = dateRangePicker.querySelector('[data-date-toggle]');
    const popup = dateRangePicker.querySelector('.date-range-popup');
    const monthLabel = dateRangePicker.querySelector('[data-date-month]');
    const grid = dateRangePicker.querySelector('[data-date-grid]');
    const monthNames = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
    const parseDate = (value) => value ? new Date(`${value}T00:00:00`) : null;
    const formatDate = (value) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
    let selectedFrom = parseDate(dateRangePicker.dataset.from);
    let selectedTo = parseDate(dateRangePicker.dataset.to);
    let currentMonth = new Date((selectedFrom || new Date()).getFullYear(), (selectedFrom || new Date()).getMonth(), 1);

    const updateToggle = () => {
        toggle.textContent = selectedFrom
            ? `${formatDate(selectedFrom)}${selectedTo ? ` — ${formatDate(selectedTo)}` : ''}`
            : 'Выбрать даты';
    };

    const renderCalendar = () => {
        monthLabel.textContent = `${monthNames[currentMonth.getMonth()]} ${currentMonth.getFullYear()}`;
        grid.replaceChildren();
        const firstWeekday = (new Date(currentMonth.getFullYear(), currentMonth.getMonth(), 1).getDay() + 6) % 7;
        const daysInMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 0).getDate();
        for (let index = 0; index < firstWeekday; index += 1) {
            grid.appendChild(document.createElement('span'));
        }
        for (let day = 1; day <= daysInMonth; day += 1) {
            const value = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), day);
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = day;
            button.dataset.date = formatDate(value);
            if (selectedFrom && button.dataset.date === formatDate(selectedFrom)) {
                button.classList.add('is-start');
            }
            if (selectedTo && button.dataset.date === formatDate(selectedTo)) {
                button.classList.add('is-end');
            }
            if (selectedFrom && selectedTo && value > selectedFrom && value < selectedTo) {
                button.classList.add('in-range');
            }
            button.addEventListener('click', () => {
                if (!selectedFrom || (selectedFrom && selectedTo)) {
                    selectedFrom = value;
                    selectedTo = null;
                } else if (value < selectedFrom) {
                    selectedTo = selectedFrom;
                    selectedFrom = value;
                } else {
                    selectedTo = value;
                }
                fromInput.value = formatDate(selectedFrom);
                toInput.value = selectedTo ? formatDate(selectedTo) : '';
                updateToggle();
                renderCalendar();
            });
            grid.appendChild(button);
        }
    };

    toggle.addEventListener('click', () => {
        popup.hidden = !popup.hidden;
        renderCalendar();
    });
    popup.addEventListener('click', (event) => event.stopPropagation());
    dateRangePicker.querySelector('[data-date-prev]').addEventListener('click', () => {
        currentMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1);
        renderCalendar();
    });
    dateRangePicker.querySelector('[data-date-next]').addEventListener('click', () => {
        currentMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1);
        renderCalendar();
    });
    dateRangePicker.querySelector('[data-date-clear]').addEventListener('click', () => {
        selectedFrom = null;
        selectedTo = null;
        fromInput.value = '';
        toInput.value = '';
        updateToggle();
        renderCalendar();
    });
    dateRangePicker.querySelector('[data-date-close]').addEventListener('click', () => {
        popup.hidden = true;
    });
    document.addEventListener('click', (event) => {
        if (!dateRangePicker.contains(event.target)) {
            popup.hidden = true;
        }
    });
    updateToggle();
}

document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
        if (!window.confirm(form.dataset.confirm)) {
            event.preventDefault();
        }
    });
});
