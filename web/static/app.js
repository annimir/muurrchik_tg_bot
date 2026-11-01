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
