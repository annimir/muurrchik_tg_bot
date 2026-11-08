const wishPullButton = document.querySelector('#wish-pull');
if (wishPullButton) {
    const animation = document.querySelector('#wish-animation');
    const results = document.querySelector('#wish-results');
    const skipButton = document.querySelector('#wish-skip');
    const csrfToken = document.querySelector('input[name="csrf_token"]').value;
    let canvasAnimation;

    const showWishToast = (message, isError = false) => {
        if (typeof showAdminToast === 'function') {
            showAdminToast(message, isError);
            return;
        }
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
    };

    const showWishError = (message) => showWishToast(message, true);

    const updateParticipant = (participant) => {
        document.querySelector('#wish-remaining').textContent = participant.remaining;
        document.querySelector('#wish-pity5').textContent = participant.pity5;
        document.querySelector('#wish-pity4').textContent = participant.pity4;
        document.querySelector('#wish-guarantee').textContent = participant.featured5_guaranteed
            ? 'Следующий 5★ гарантированно featured'
            : '50/50 на следующий 5★';
        wishPullButton.disabled = participant.remaining < 10;
    };

    const updateRewards = (rules, summary) => {
        document.querySelector('#wish-bonus-today').textContent = summary.today;
        document.querySelector('#wish-bonus-total').textContent = summary.total;
        rules.forEach((rule) => {
            const card = document.querySelector(`[data-reward-code="${rule.code}"]`);
            if (!card) {
                return;
            }
            card.classList.toggle('is-complete', rule.completed);
            const progress = card.querySelector('progress');
            progress.max = rule.threshold;
            progress.value = rule.progress;
            card.querySelector('[data-reward-progress]').textContent = `${rule.progress}/${rule.threshold}`;
            let status = rule.completed ? 'Награда получена' : 'Можно выполнить';
            if (rule.monthly_reached) {
                status = 'Месячный лимит исчерпан';
            } else if (!rule.completed && rule.daily_limit) {
                status = `Сегодня: до ${rule.daily_limit} наград(ы)`;
            }
            if (rule.monthly_limit) {
                status += ` · За ивент получено: ${rule.earned}`;
            }
            card.querySelector('[data-reward-status]').textContent = status;
        });
    };

    const updateStats = (stats) => {
        const body = document.querySelector('#wish-stats-body');
        body.replaceChildren();
        if (!stats.length) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 10;
            cell.textContent = 'Пока никто не сделал молитв.';
            row.appendChild(cell);
            body.appendChild(row);
            return;
        }
        stats.forEach((stat) => {
            const row = document.createElement('tr');
            const average = stat.average_five_pity === null ? '—' : Number(stat.average_five_pity).toFixed(1);
            const values = [
                stat.tag || stat.id, stat.used, stat.remaining, stat.five_star_count,
                stat.featured_five_count, stat.four_star_count, stat.three_star_count,
                average, `${stat.pity5} / ${stat.pity4}`,
                stat.remaining === 0 ? 'Участвует' : 'Нужно использовать все молитвы',
            ];
            values.forEach((value) => {
                const cell = document.createElement('td');
                cell.textContent = value;
                row.appendChild(cell);
            });
            body.appendChild(row);
        });
    };

    const updateHistory = (drops) => {
        const history = document.querySelector('#wish-history');
        if (history.querySelector('.muted')) {
            history.replaceChildren();
        }
        [...drops].reverse().forEach((drop) => {
            const badge = document.createElement('span');
            badge.className = `badge wish-rarity-${drop.rarity}`;
            badge.textContent = `${drop.name} · ${drop.rarity}★`;
            history.prepend(badge);
        });
    };

    const showResults = (drops) => {
        results.replaceChildren();
        [...drops].sort((first, second) => second.rarity - first.rarity).forEach((drop, index) => {
            const card = document.createElement('div');
            card.className = `wish-result-card wish-rarity-${drop.rarity}`;
            card.style.animationDelay = `${index * 45}ms`;
            const topStar = document.createElement('span');
            topStar.className = 'wish-card-top-star';
            topStar.textContent = '✧';
            let visual;
            if (drop.image_url) {
                visual = document.createElement('img');
                visual.className = 'wish-item-image';
                visual.src = drop.image_url;
                visual.alt = drop.name;
                visual.loading = 'lazy';
            } else {
                visual = document.createElement('span');
                visual.className = 'wish-item-monogram';
                visual.textContent = drop.name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2);
            }
            const name = document.createElement('strong');
            name.textContent = drop.name;
            const type = document.createElement('small');
            type.textContent = drop.item_type === 'character' ? 'Персонаж' : 'Оружие';
            const rarity = document.createElement('span');
            rarity.className = 'wish-card-rarity';
            rarity.textContent = '★'.repeat(drop.rarity);
            card.append(topStar, visual, name, type, rarity);
            if (drop.featured && drop.rarity >= 4) {
                const featured = document.createElement('small');
                featured.className = 'wish-featured-label';
                featured.textContent = 'Featured';
                card.appendChild(featured);
            }
            if (drop.radiant) {
                const radiant = document.createElement('small');
                radiant.className = 'wish-radiant-label';
                radiant.textContent = 'Capturing Radiance';
                card.appendChild(radiant);
            }
            results.appendChild(card);
        });
        animation.hidden = true;
        animation.setAttribute('aria-hidden', 'true');
        skipButton.hidden = true;
    };

    const playAnimation = (drops) => {
        animation.replaceChildren();
        const highestRarity = Math.max(...drops.map((drop) => drop.rarity));
        animation.className = `wish-animation wish-animation-${highestRarity}`;
        animation.hidden = false;
        animation.setAttribute('aria-hidden', 'false');
        skipButton.hidden = false;
        const finish = () => {
            if (canvasAnimation) {
                canvasAnimation.destroy();
                canvasAnimation = null;
            }
            showResults(drops);
        };
        skipButton.onclick = finish;
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches
            || typeof WishCanvasAnimation !== 'function') {
            finish();
            return;
        }
        canvasAnimation = new WishCanvasAnimation(animation, {
            rarity: highestRarity,
            radiant: drops.some((drop) => drop.radiant),
            onComplete: finish,
        });
        canvasAnimation.start();
    };

    wishPullButton.addEventListener('click', async () => {
        wishPullButton.disabled = true;
        const body = new FormData();
        body.append('banner_id', wishPullButton.dataset.bannerId);
        body.append('csrf_token', csrfToken);
        try {
            const response = await fetch(`/wishes/${wishPullButton.dataset.eventId}/pull`, {
                method: 'POST',
                body,
                headers: {'X-Requested-With': 'XMLHttpRequest'},
                credentials: 'same-origin',
            });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.detail || 'Не удалось выполнить молитву');
            }
            updateParticipant(payload.participant);
            updateStats(payload.stats);
            updateHistory(payload.drops);
            updateRewards(payload.reward_rules, payload.reward_summary);
            if (payload.rewards.length) {
                const total = payload.rewards.reduce((sum, reward) => sum + reward.amount, 0);
                const details = payload.rewards.map((reward) => reward.title).join(', ');
                showWishToast(`Получено +${total} бонусных молитв: ${details}`);
            }
            playAnimation(payload.drops);
        } catch (error) {
            showWishError(error.message);
            wishPullButton.disabled = false;
        }
    });
}
