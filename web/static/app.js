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
        const label = trigger.querySelector('[data-media-label]');
        const defaultLabel = label?.textContent;
        trigger.addEventListener('click', async (event) => {
            event.preventDefault();
            event.stopPropagation();
            content.replaceChildren();
            if (label) {
                label.textContent = defaultLabel;
            }
            let source = trigger.dataset.mediaOpen;
            if (trigger.dataset.mediaResolve === 'true') {
                trigger.disabled = true;
                trigger.setAttribute('aria-busy', 'true');
                if (label) {
                    label.textContent = 'Загружаем плеер…';
                }
                try {
                    const response = await fetch(source, {
                        headers: {'X-Requested-With': 'XMLHttpRequest'},
                        credentials: 'same-origin',
                    });
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    source = (await response.json()).url;
                } catch (error) {
                    if (label) {
                        label.textContent = 'Плеер недоступен. Откройте оригинал ниже';
                    }
                    return;
                } finally {
                    trigger.disabled = false;
                    trigger.setAttribute('aria-busy', 'false');
                }
            }
            let media;
            if (trigger.dataset.mediaKind === 'video') {
                media = document.createElement('video');
                media.controls = true;
                media.playsInline = true;
                configureVideo(media);
            } else if (trigger.dataset.mediaKind === 'embed') {
                media = document.createElement('iframe');
                media.className = 'media-embed';
                media.classList.toggle('is-vertical', trigger.dataset.mediaVertical === 'true');
                media.title = `Видео ${trigger.dataset.mediaPlatform}`;
                media.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
                media.allowFullscreen = true;
                media.referrerPolicy = 'strict-origin-when-cross-origin';
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

function configureFilterDropdown(dropdown) {
    const toggle = dropdown.querySelector('[data-filter-toggle]');
    const popup = dropdown.querySelector('.filter-popup');
    const inputs = [...dropdown.querySelectorAll('.filter-option input')];
    const updateToggle = () => {
        const checked = inputs.filter((input) => input.checked);
        if (dropdown.matches('[data-tag-filter]')) {
            toggle.textContent = checked.length
                ? checked.map((input) => input.nextElementSibling.textContent).join(', ')
                : 'Все теги';
            dropdown.classList.toggle('has-value', checked.length > 0);
        } else {
            toggle.textContent = checked.length
                ? checked.map((input) => input.nextElementSibling.textContent).join(', ')
                : dropdown.dataset.defaultLabel;
            const defaultValue = dropdown.dataset.defaultValue || '';
            dropdown.classList.toggle(
                'has-value', checked.some((input) => input.value !== defaultValue),
            );
        }
    };
    toggle.addEventListener('click', () => {
        popup.hidden = !popup.hidden;
        toggle.setAttribute('aria-expanded', String(!popup.hidden));
        if (!popup.hidden) {
            dropdown.querySelector('[data-tag-search]')?.focus();
        }
    });
    dropdown.querySelector('[data-filter-close]').addEventListener('click', () => {
        popup.hidden = true;
        toggle.setAttribute('aria-expanded', 'false');
    });
    inputs.forEach((input) => input.addEventListener('change', updateToggle));
    dropdown.querySelector('[data-tags-clear]')?.addEventListener('click', () => {
        inputs.forEach((input) => { input.checked = false; });
        updateToggle();
    });
    const search = dropdown.querySelector('[data-tag-search]');
    if (search) {
        const options = [...dropdown.querySelectorAll('[data-tag-option]')];
        const empty = dropdown.querySelector('[data-tag-empty]');
        let searchTimer;
        let searchController;

        const showOptions = (matchingIds = null, failed = false) => {
            let visible = 0;
            options.forEach((option) => {
                const tagId = option.querySelector('input').value;
                option.hidden = matchingIds !== null && !matchingIds.has(tagId);
                if (!option.hidden) {
                    visible += 1;
                }
            });
            empty.textContent = failed ? 'Не удалось выполнить поиск' : 'Теги не найдены.';
            empty.hidden = visible > 0;
        };

        const searchTags = async () => {
            const query = search.value.trim();
            if (searchController) {
                searchController.abort();
            }
            if (!query) {
                showOptions();
                return;
            }
            searchController = new AbortController();
            try {
                const response = await fetch(`/tags/search?q=${encodeURIComponent(query)}`, {
                    signal: searchController.signal,
                    credentials: 'same-origin',
                });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const payload = await response.json();
                showOptions(new Set(payload.tags.map((tag) => String(tag.id))));
            } catch (error) {
                if (error.name !== 'AbortError') {
                    showOptions(new Set(), true);
                }
            }
        };

        search.addEventListener('input', () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(searchTags, 200);
        });
    }
    updateToggle();
}

document.querySelectorAll('[data-filter-dropdown]').forEach(configureFilterDropdown);

document.querySelectorAll('[data-local-search]').forEach((search) => {
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
});

function configureDateRangePicker(dateRangePicker) {
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
        dateRangePicker.classList.toggle('has-value', Boolean(selectedFrom));
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
        toggle.setAttribute('aria-expanded', String(!popup.hidden));
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
        toggle.setAttribute('aria-expanded', 'false');
    });
    updateToggle();
}

document.querySelectorAll('[data-date-range]').forEach(configureDateRangePicker);

document.addEventListener('click', (event) => {
    document.querySelectorAll('[data-date-range], [data-filter-dropdown]').forEach((dropdown) => {
        if (!dropdown.contains(event.target)) {
            const popup = dropdown.querySelector('.date-range-popup, .filter-popup');
            popup.hidden = true;
            dropdown.querySelector('[data-date-toggle], [data-filter-toggle]')?.setAttribute('aria-expanded', 'false');
        }
    });
});

const tagUsagePanel = document.querySelector('[data-tag-usage-panel]');
if (tagUsagePanel) {
    let usageController;

    const showUsageError = (message) => {
        const error = tagUsagePanel.querySelector('[data-usage-error]');
        error.textContent = message;
        error.hidden = !message;
    };

    const loadTagUsage = async (params) => {
        if (usageController) {
            usageController.abort();
        }
        const controller = new AbortController();
        usageController = controller;
        tagUsagePanel.setAttribute('aria-busy', 'true');
        showUsageError('');
        try {
            const response = await fetch(`/admin/tag-usage/fragment?${params}`, {
                signal: controller.signal,
                headers: {'X-Requested-With': 'XMLHttpRequest'},
                credentials: 'same-origin',
            });
            if (!response.ok) {
                const payload = await response.json();
                throw new Error(payload.detail || 'Не удалось обновить график');
            }
            const payload = await response.json();
            tagUsagePanel.innerHTML = payload.html;
            tagUsagePanel.querySelectorAll('[data-date-range]').forEach(configureDateRangePicker);
            history.replaceState(null, '', `/admin?${params}`);
            tagUsagePanel.querySelector(`[data-period="${params.get('period')}"]`)?.focus({preventScroll: true});
        } catch (error) {
            if (error.name !== 'AbortError') {
                showUsageError(error.message);
            }
        } finally {
            if (usageController === controller) {
                tagUsagePanel.setAttribute('aria-busy', 'false');
            }
        }
    };

    tagUsagePanel.addEventListener('click', (event) => {
        const button = event.target.closest('[data-period]');
        if (!button) {
            return;
        }
        const params = new URLSearchParams({period: button.dataset.period});
        if (button.dataset.period === 'custom') {
            const now = new Date();
            const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
            params.set('date_from', tagUsagePanel.querySelector('input[name="date_from"]')?.value || today);
            params.set('date_to', tagUsagePanel.querySelector('input[name="date_to"]')?.value || today);
        }
        loadTagUsage(params);
    });

    tagUsagePanel.addEventListener('submit', (event) => {
        if (!event.target.matches('[data-usage-form]')) {
            return;
        }
        event.preventDefault();
        const formData = new FormData(event.target);
        const dateFrom = formData.get('date_from');
        const dateTo = formData.get('date_to');
        if (!dateFrom || !dateTo) {
            showUsageError('Выберите даты начала и окончания периода');
            return;
        }
        loadTagUsage(new URLSearchParams({period: 'custom', date_from: dateFrom, date_to: dateTo}));
    });
}

document.querySelectorAll('[data-mobile-filters]').forEach((filters) => {
    const toggle = filters.querySelector('[data-filters-toggle]');
    toggle.addEventListener('click', () => {
        const collapsed = filters.classList.toggle('is-mobile-collapsed');
        toggle.setAttribute('aria-expanded', String(!collapsed));
        toggle.textContent = collapsed ? 'Показать фильтры' : 'Скрыть фильтры';
    });
});

const commandSearch = document.querySelector('[data-command-search]');
if (commandSearch) {
    const cards = [...document.querySelectorAll('[data-command-card]')];
    const groups = [...document.querySelectorAll('[data-command-group]')];
    const resultCount = document.querySelector('[data-command-count]');
    const emptyState = document.querySelector('[data-commands-empty]');

    commandSearch.addEventListener('input', () => {
        const query = commandSearch.value.trim().toLocaleLowerCase('ru');
        let visible = 0;
        cards.forEach((card) => {
            card.hidden = Boolean(query) && !card.dataset.commandSearchText.includes(query);
            if (!card.hidden) {
                visible += 1;
            }
        });
        groups.forEach((group) => {
            const hasVisibleCommands = Boolean(group.querySelector('[data-command-card]:not([hidden])'));
            group.hidden = !hasVisibleCommands;
            if (group.matches('details')) {
                group.open = Boolean(query) && hasVisibleCommands;
            }
        });
        resultCount.textContent = query ? `Найдено: ${visible}` : `Команд: ${visible}`;
        emptyState.hidden = visible > 0;
    });
}

document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
        if (!window.confirm(form.dataset.confirm)) {
            event.preventDefault();
        }
    });
});
