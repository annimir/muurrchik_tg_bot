const tierlistExportButton = document.querySelector('[data-export-tierlist]');

if (tierlistExportButton) {
    const board = document.querySelector('[data-tierlist-board]');
    const status = document.querySelector('[data-export-status]');

    const loadImage = (source) => new Promise((resolve, reject) => {
        const image = new Image();
        image.addEventListener('load', () => resolve(image));
        image.addEventListener('error', () => reject(new Error(`Не удалось загрузить ${source}`)));
        image.src = source;
    });

    const textLines = (context, text, maxWidth, maxLines = 2) => {
        const words = text.split(/\s+/);
        const lines = [];
        let line = '';
        for (const word of words) {
            const candidate = line ? `${line} ${word}` : word;
            if (context.measureText(candidate).width <= maxWidth || !line) {
                line = candidate;
            } else {
                lines.push(line);
                line = word;
            }
        }
        if (line) {
            lines.push(line);
        }
        if (lines.length > maxLines) {
            const visible = lines.slice(0, maxLines);
            visible[maxLines - 1] = `${visible[maxLines - 1].replace(/[.,;:]?$/, '')}…`;
            return visible;
        }
        return lines;
    };

    const roundedImage = (context, image, x, y, size) => {
        const side = Math.min(image.naturalWidth, image.naturalHeight);
        context.save();
        context.beginPath();
        context.roundRect(x, y, size, size, 7);
        context.clip();
        context.drawImage(
            image,
            (image.naturalWidth - side) / 2,
            (image.naturalHeight - side) / 2,
            side,
            side,
            x,
            y,
            size,
            size,
        );
        context.restore();
    };

    tierlistExportButton.addEventListener('click', async () => {
        tierlistExportButton.disabled = true;
        tierlistExportButton.textContent = 'Готовим PNG…';
        status.textContent = '';
        try {
            const rows = [...board.querySelectorAll('.tier-row:not([hidden])')].map((row) => ({
                code: row.querySelector('header h2').textContent.trim(),
                color: getComputedStyle(row.querySelector('header')).backgroundColor,
                characters: [...row.querySelectorAll('.tier-character:not([hidden])')].map((character) => ({
                    name: character.querySelector('strong').textContent.trim(),
                    source: new URL(character.querySelector('img').getAttribute('src'), document.baseURI).href,
                })),
            }));
            const images = new Map();
            await Promise.all(rows.flatMap((row) => row.characters.map(async (character) => {
                images.set(character.source, await loadImage(character.source));
            })));

            const margin = 32;
            const headerHeight = 164;
            const tierWidth = 88;
            const columns = 8;
            const cellWidth = 112;
            const cellHeight = 122;
            const width = margin * 2 + tierWidth + columns * cellWidth;
            const exportRows = rows.map((row) => ({
                ...row,
                height: Math.max(118, Math.ceil(row.characters.length / columns) * cellHeight + 20),
            }));
            const height = headerHeight + exportRows.reduce((sum, row) => sum + row.height + 10, 0) + margin;
            const canvas = document.createElement('canvas');
            canvas.width = width * 2;
            canvas.height = height * 2;
            const context = canvas.getContext('2d');
            context.scale(2, 2);
            context.fillStyle = '#0c1627';
            context.fillRect(0, 0, width, height);

            context.fillStyle = '#d8bc72';
            context.font = '700 13px sans-serif';
            context.fillText(board.dataset.games.toUpperCase(), margin, 36);
            context.fillStyle = '#f2dfa3';
            context.font = '34px Georgia, serif';
            const titleLines = textLines(context, board.dataset.title, width - margin * 2, 2);
            titleLines.forEach((line, index) => context.fillText(line, margin, 76 + index * 34));
            context.fillStyle = '#b8c2cf';
            context.font = '15px sans-serif';
            context.fillText(`Автор: ${board.dataset.author}`, margin, 146);

            let rowY = headerHeight;
            for (const row of exportRows) {
                context.fillStyle = '#101e31';
                context.fillRect(margin, rowY, width - margin * 2, row.height);
                context.fillStyle = row.color;
                context.fillRect(margin, rowY, tierWidth, row.height);
                context.strokeStyle = 'rgba(216, 188, 114, .28)';
                context.strokeRect(margin + 0.5, rowY + 0.5, width - margin * 2 - 1, row.height - 1);
                context.fillStyle = '#f2dfa3';
                context.font = '30px Georgia, serif';
                context.textAlign = 'center';
                context.fillText(row.code, margin + tierWidth / 2, rowY + 48);
                context.textAlign = 'left';

                row.characters.forEach((character, index) => {
                    const column = index % columns;
                    const line = Math.floor(index / columns);
                    const x = margin + tierWidth + column * cellWidth + 12;
                    const y = rowY + 10 + line * cellHeight;
                    roundedImage(context, images.get(character.source), x, y, 86);
                    context.fillStyle = '#f6f1e5';
                    context.font = '12px sans-serif';
                    const nameLines = textLines(context, character.name, 92, 2);
                    nameLines.forEach((nameLine, lineIndex) => {
                        context.fillText(nameLine, x - 2, y + 102 + lineIndex * 14);
                    });
                });
                rowY += row.height + 10;
            }

            const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
            if (!blob) {
                throw new Error('Canvas не вернул PNG');
            }
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            const filename = board.dataset.title.replace(/[<>:"/\\|?*\x00-\x1F]/g, '').trim() || 'tierlist';
            link.href = url;
            link.download = `${filename}.png`;
            link.click();
            window.setTimeout(() => URL.revokeObjectURL(url), 1000);
            status.textContent = 'PNG сохранён';
        } catch (error) {
            status.textContent = 'Не удалось создать PNG. Попробуйте ещё раз.';
        } finally {
            tierlistExportButton.disabled = false;
            tierlistExportButton.textContent = 'Экспортировать в PNG';
        }
    });
}
